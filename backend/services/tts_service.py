"""
TTS service — swappable text-to-speech backend.

Primary backend: Pocket TTS (Kyutai, CPU-native, expressive, ~24kHz).
Fallback backend: Kokoro (Apache 2.0, ~82M params, fast CPU).

Pocket TTS built-in voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma
The `voice` param should be one of those names. Unknown names fall back to "marius" (male).
Kokoro voice names (e.g. "am_adam") are used if Pocket TTS is unavailable.

Output: OGG Opus bytes ready to send as a WhatsApp voice note.
Requires (Pocket TTS): pip install pocket-tts torch scipy  (via uv sync)
Requires (Kokoro fallback): pip install kokoro soundfile numpy
Requires system: ffmpeg (for WAV→OGG Opus conversion)
"""
import io
import logging
import os
import re
import subprocess
import asyncio

logger = logging.getLogger(__name__)

# Resolve ffmpeg binary — check PATH first, then common winget install locations
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
    # winget installs to a versioned path — glob for it
    import glob
    winget_base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(winget_base):
        matches = glob.glob(os.path.join(winget_base, "**", "ffmpeg.exe"), recursive=True)
        candidates = matches + candidates
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "ffmpeg"  # fall through and let subprocess raise a clear error

FFMPEG_BIN = _find_ffmpeg()

# Pocket TTS voices (built-in, no reference audio needed)
POCKET_VOICES = {"alba", "marius", "javert", "jean", "fantine", "cosette", "eponine", "azelma"}
# Male voices for default selection
POCKET_MALE_DEFAULT = "marius"

_pocket_model = None
_pocket_available = None  # None = untested, True/False after first attempt
_pocket_voice_states: dict = {}  # cache: voice_name -> voice_state

_kokoro_pipeline = None


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_for_tts(text: str) -> str:
    """Strip markdown and other non-speakable content before synthesis."""
    # Remove code blocks entirely
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove markdown formatting characters
    text = re.sub(r"[*_~>#|]+", "", text)
    # Remove markdown headers
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Pocket TTS ────────────────────────────────────────────────────────────────

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
    # Map unknown voices to male default
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

    # Normalise to int16 if float
    if audio_np.dtype != "int16":
        audio_np = (audio_np * 32767).clip(-32768, 32767).astype("int16")

    buf = io.BytesIO()
    scipy.io.wavfile.write(buf, model.sample_rate, audio_np)
    return buf.getvalue()


# ── Kokoro (fallback) ─────────────────────────────────────────────────────────

def _get_kokoro():
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        from kokoro import KPipeline
        _kokoro_pipeline = KPipeline(lang_code="a")  # 'a' = American English
    return _kokoro_pipeline


def _synthesize_kokoro(text: str, voice: str = "am_adam") -> bytes:
    import numpy as np
    import soundfile as sf

    # Pocket TTS voice names aren't valid Kokoro voices — use default
    kokoro_voice = voice if voice not in POCKET_VOICES else "am_adam"

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

def _wav_to_ogg_opus(wav_bytes: bytes) -> bytes:
    proc = subprocess.run(
        [
            FFMPEG_BIN, "-y",
            "-f", "wav", "-i", "pipe:0",
            "-c:a", "libopus",
            "-b:a", "32k",
            "-vbr", "on",
            "-f", "ogg",
            "pipe:1",
        ],
        input=wav_bytes,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode()[:200]}")
    return proc.stdout


def _run_synthesis(text: str, voice: str) -> bytes:
    # Try Pocket TTS first
    try:
        wav = _synthesize_pocket(text, voice)
        logger.debug("Synthesized with Pocket TTS (voice=%s)", voice)
        return _wav_to_ogg_opus(wav)
    except Exception as e:
        logger.warning("Pocket TTS failed, falling back to Kokoro: %s", e)

    wav = _synthesize_kokoro(text, voice=voice)
    logger.debug("Synthesized with Kokoro (voice=%s)", voice)
    return _wav_to_ogg_opus(wav)


async def synthesize(text: str, voice: str = POCKET_MALE_DEFAULT) -> bytes:
    """Async entry point. Returns OGG Opus bytes ready for WhatsApp."""
    clean = _clean_for_tts(text)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_synthesis, clean, voice)
