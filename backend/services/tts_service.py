"""
TTS service — multi-backend text-to-speech with automatic selection.

Backend selection (in priority order):
  1. Qwen3-TTS  — high quality, requires CUDA GPU + qwen-tts package
  2. Pocket TTS  — CPU-native, expressive (~24kHz) [classic fallback]
  3. Kokoro      — CPU, fast, lightweight [last resort]

Qwen3 preset voices (CustomVoice model):
  English : Ryan, Aiden
  Chinese : Vivian, Serena, Uncle_Fu, Dylan, Eric
  Japanese: Ono_Anna
  Korean  : Sohee

Pocket TTS built-in voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma

Environment variables:
  QWEN_TTS_SIZE    — "0.6B" (default) or "1.7B"
  QWEN_TTS_DEVICE  — "cuda:0" (default)

Output: OGG Opus bytes ready to send as a WhatsApp voice note.
"""
import io
import logging
import os
import re
import subprocess
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

QWEN_TTS_SIZE   = os.environ.get("QWEN_TTS_SIZE", "0.6B")
QWEN_TTS_DEVICE = os.environ.get("QWEN_TTS_DEVICE", "cuda:0")

QWEN_CUSTOM_VOICE_MODEL = f"Qwen/Qwen3-TTS-12Hz-{QWEN_TTS_SIZE}-CustomVoice"
QWEN_BASE_MODEL         = f"Qwen/Qwen3-TTS-12Hz-{QWEN_TTS_SIZE}-Base"

# Qwen preset voices (CustomVoice model)
QWEN_VOICES = {"Ryan", "Aiden", "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ono_Anna", "Sohee"}
QWEN_DEFAULT_VOICE = "Ryan"

# Pocket TTS voices (classic CPU backend)
POCKET_VOICES = {"alba", "marius", "javert", "jean", "fantine", "cosette", "eponine", "azelma"}
POCKET_MALE_DEFAULT = "marius"

# ── ffmpeg ────────────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    import glob
    winget_base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(winget_base):
        matches = glob.glob(os.path.join(winget_base, "**", "ffmpeg.exe"), recursive=True)
        candidates = matches + candidates
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "ffmpeg"

FFMPEG_BIN = _find_ffmpeg()

# ── Globals ───────────────────────────────────────────────────────────────────

_qwen_custom_model      = None
_qwen_base_model        = None
_qwen_custom_available  = None   # None = untested, True/False after first attempt
_qwen_base_available    = None
# Cache: (audio_path_or_hash, ref_text) -> voice_clone_prompt object
_voice_clone_prompt_cache: dict = {}

_pocket_model       = None
_pocket_available   = None
_pocket_voice_states: dict = {}

_kokoro_pipeline    = None


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_for_tts(text: str) -> str:
    """Strip markdown and other non-speakable content before synthesis."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_~>#|]+", "", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── GPU detection ─────────────────────────────────────────────────────────────

def _has_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


# ── Qwen3-TTS ─────────────────────────────────────────────────────────────────

def _load_qwen_model(model_name: str):
    """Load a Qwen3TTSModel directly onto the target device."""
    import torch
    from qwen_tts import Qwen3TTSModel
    kwargs = dict(dtype=torch.bfloat16, device_map=QWEN_TTS_DEVICE, low_cpu_mem_usage=False)
    try:
        kwargs["attn_implementation"] = "flash_attention_2"
        return Qwen3TTSModel.from_pretrained(model_name, **kwargs)
    except Exception:
        kwargs.pop("attn_implementation", None)
        return Qwen3TTSModel.from_pretrained(model_name, **kwargs)


def _get_qwen_custom():
    global _qwen_custom_model, _qwen_custom_available
    if _qwen_custom_available is False:
        raise RuntimeError("Qwen3-TTS not available")
    if _qwen_custom_model is not None:
        return _qwen_custom_model
    try:
        _qwen_custom_model = _load_qwen_model(QWEN_CUSTOM_VOICE_MODEL)
        _qwen_custom_available = True
        logger.info("Qwen3-TTS CustomVoice loaded (%s)", QWEN_CUSTOM_VOICE_MODEL)
        return _qwen_custom_model
    except Exception as e:
        _qwen_custom_available = False
        raise RuntimeError(f"Qwen3-TTS unavailable: {e}") from e


def _get_qwen_base():
    global _qwen_base_model, _qwen_base_available
    if _qwen_base_available is False:
        raise RuntimeError("Qwen3-TTS not available")
    if _qwen_base_model is not None:
        return _qwen_base_model
    try:
        _qwen_base_model = _load_qwen_model(QWEN_BASE_MODEL)
        _qwen_base_available = True
        logger.info("Qwen3-TTS Base loaded (%s)", QWEN_BASE_MODEL)
        return _qwen_base_model
    except Exception as e:
        _qwen_base_available = False
        raise RuntimeError(f"Qwen3-TTS Base unavailable: {e}") from e


def _get_voice_clone_prompt(model, ref_audio: str, ref_text: str):
    """Return cached voice clone prompt, computing it on first call."""
    cache_key = (ref_audio, ref_text)
    if cache_key not in _voice_clone_prompt_cache:
        logger.debug("Computing voice clone prompt for %s", ref_audio)
        _voice_clone_prompt_cache[cache_key] = model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
    return _voice_clone_prompt_cache[cache_key]


def _synthesize_qwen_clone(text: str, ref_audio: str, ref_text: str) -> bytes:
    import soundfile as sf
    model = _get_qwen_base()
    prompt = _get_voice_clone_prompt(model, ref_audio, ref_text)
    wavs, sr = model.generate_voice_clone(
        text=text,
        language="Auto",
        voice_clone_prompt=prompt,
    )
    buf = io.BytesIO()
    sf.write(buf, wavs[0], sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _synthesize_qwen_custom(text: str, voice: str) -> bytes:
    import soundfile as sf
    resolved = voice if voice in QWEN_VOICES else QWEN_DEFAULT_VOICE
    model = _get_qwen_custom()
    wavs, sr = model.generate_custom_voice(
        text=text,
        language="Auto",
        speaker=resolved,
    )
    buf = io.BytesIO()
    sf.write(buf, wavs[0], sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ── Pocket TTS (classic CPU) ──────────────────────────────────────────────────

def _get_pocket():
    global _pocket_model, _pocket_available
    if _pocket_available is False:
        raise RuntimeError("Pocket TTS not available")
    if _pocket_model is not None:
        return _pocket_model
    try:
        from pocket_tts import TTSModel
        _pocket_model = TTSModel.load_model()
        _pocket_available = True
        logger.info("Pocket TTS loaded successfully")
        return _pocket_model
    except Exception as e:
        _pocket_available = False
        raise RuntimeError(f"Pocket TTS unavailable: {e}") from e


def _get_pocket_voice_state(model, voice: str):
    global _pocket_voice_states
    resolved = voice if voice in POCKET_VOICES else POCKET_MALE_DEFAULT
    if resolved not in _pocket_voice_states:
        _pocket_voice_states[resolved] = model.get_state_for_audio_prompt(resolved)
    return _pocket_voice_states[resolved]


def _synthesize_pocket(text: str, voice: str) -> bytes:
    import scipy.io.wavfile
    import numpy as np
    model = _get_pocket()
    voice_state = _get_pocket_voice_state(model, voice)
    audio_tensor = model.generate_audio(voice_state, text)
    audio_np = audio_tensor.numpy()
    if audio_np.dtype != "int16":
        audio_np = (audio_np * 32767).clip(-32768, 32767).astype("int16")
    buf = io.BytesIO()
    scipy.io.wavfile.write(buf, model.sample_rate, audio_np)
    return buf.getvalue()


# ── Kokoro (last resort CPU) ──────────────────────────────────────────────────

def _get_kokoro():
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        from kokoro import KPipeline
        _kokoro_pipeline = KPipeline(lang_code="a")
    return _kokoro_pipeline


def _synthesize_kokoro(text: str, voice: str = "am_adam") -> bytes:
    import numpy as np
    import soundfile as sf
    kokoro_voice = voice if voice not in POCKET_VOICES and voice not in QWEN_VOICES else "am_adam"
    pipeline = _get_kokoro()
    audio_chunks = []
    for _, _, audio in pipeline(text, voice=kokoro_voice, speed=1.0):
        if audio is not None:
            audio_chunks.append(audio)
    if not audio_chunks:
        raise RuntimeError("Kokoro produced no audio")
    samples = np.concatenate(audio_chunks)
    buf = io.BytesIO()
    sf.write(buf, samples, samplerate=24000, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ── Shared ────────────────────────────────────────────────────────────────────

def _wav_to_ogg_opus(wav_bytes: bytes, speed: float = 1.0) -> bytes:
    cmd = [FFMPEG_BIN, "-y", "-f", "wav", "-i", "pipe:0"]
    if speed != 1.0:
        cmd += ["-af", f"atempo={speed:.3f}"]
    cmd += ["-c:a", "libopus", "-b:a", "32k", "-vbr", "on", "-f", "ogg", "pipe:1"]
    proc = subprocess.run(cmd, input=wav_bytes, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode()[:200]}")
    return proc.stdout


def _run_synthesis(
    text: str,
    voice: str,
    backend: str,
    ref_audio: Optional[str],
    ref_text: Optional[str],
) -> bytes:
    """
    backend: "auto" | "qwen" | "classic"
    Voice clone is attempted when ref_audio + ref_text are provided AND backend allows Qwen3.
    """
    use_qwen = backend == "qwen" or (backend != "classic" and _has_cuda())

    if use_qwen:
        # Voice clone path — auto-transcribe ref audio if no transcript provided
        if ref_audio and os.path.isfile(ref_audio):
            try:
                actual_ref_text = ref_text or ""
                if not actual_ref_text:
                    try:
                        from routers.whatsapp_router import _get_whisper_model
                        _wm = _get_whisper_model()
                        import io as _io
                        with open(ref_audio, "rb") as _f:
                            _buf = _io.BytesIO(_f.read())
                        segs, _ = _wm.transcribe(_buf, beam_size=1)
                        actual_ref_text = " ".join(s.text.strip() for s in segs).strip()
                        logger.info("Auto-transcribed ref audio: %s", actual_ref_text[:80])
                    except Exception as te:
                        logger.warning("Auto-transcription failed: %s", te)
                if actual_ref_text:
                    wav = _synthesize_qwen_clone(text, ref_audio, actual_ref_text)
                    logger.debug("Synthesized with Qwen3-TTS voice clone")
                    return _wav_to_ogg_opus(wav, speed=1.08)
                else:
                    logger.warning("Skipping voice clone: ref_text required but transcription failed")
            except Exception as e:
                logger.warning("Qwen3-TTS voice clone failed, trying preset: %s", e)

        # Preset voice path
        try:
            wav = _synthesize_qwen_custom(text, voice)
            logger.debug("Synthesized with Qwen3-TTS CustomVoice (voice=%s)", voice)
            return _wav_to_ogg_opus(wav)
        except Exception as e:
            logger.warning("Qwen3-TTS failed, falling back to classic: %s", e)

    # Classic CPU fallback
    try:
        wav = _synthesize_pocket(text, voice)
        logger.debug("Synthesized with Pocket TTS (voice=%s)", voice)
        return _wav_to_ogg_opus(wav)
    except Exception as e:
        logger.warning("Pocket TTS failed, falling back to Kokoro: %s", e)

    wav = _synthesize_kokoro(text, voice=voice)
    logger.debug("Synthesized with Kokoro (voice=%s)", voice)
    return _wav_to_ogg_opus(wav)


async def synthesize(
    text: str,
    voice: str = QWEN_DEFAULT_VOICE,
    backend: str = "auto",
    ref_audio: Optional[str] = None,
    ref_text: Optional[str] = None,
) -> bytes:
    """
    Async entry point. Returns OGG Opus bytes ready for WhatsApp.

    Args:
        text      : Text to synthesize.
        voice     : Qwen preset voice name (Ryan, Aiden, …) or Pocket voice name.
        backend   : "auto" (GPU→Qwen, CPU→classic), "qwen" (force Qwen), "classic" (force CPU).
        ref_audio : Path to reference .wav for voice cloning (Qwen only).
        ref_text  : Transcript of the reference audio (required for voice cloning).
    """
    clean = _clean_for_tts(text)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _run_synthesis, clean, voice, backend, ref_audio, ref_text
    )


def invalidate_voice_clone_cache(ref_audio: str) -> None:
    """Remove all cached clone prompts for a given reference audio path."""
    keys_to_remove = [k for k in _voice_clone_prompt_cache if k[0] == ref_audio]
    for k in keys_to_remove:
        del _voice_clone_prompt_cache[k]
    if keys_to_remove:
        logger.info("Invalidated %d voice clone cache entries for %s", len(keys_to_remove), ref_audio)
