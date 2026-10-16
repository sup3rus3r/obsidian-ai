"""Core capture pipeline: load a HF checkpoint with nnsight, run one forward
pass with hooks, extract attention patterns + residual-stream activations,
apply logit lens. See the module docstring in main.py for the full framing
on what this can/cannot validly claim.

Module path assumptions (model.model.layers[i], model.model.norm,
model.lm_head) follow transformers' standard LlamaForCausalLM-style naming,
shared by Llama, Mistral, Qwen2/2.5/3, and most current open decoder-only
architectures. A model with a different module tree (e.g. GPT-2's
model.transformer.h) will fail cleanly at capture time with an attribute
error — that failure is surfaced to the caller, not silently worked around.
"""

import logging
import time
from typing import Any

import torch

logger = logging.getLogger(__name__)

# Real attention weights require attn_implementation="eager" — SDPA and
# Flash Attention are fused kernels that never materialize the full
# attention-probability matrix, by design (that's the whole point of the
# fusion), so there is nothing to capture under those backends. Confirmed
# via HF transformers' own attention_interface docs.
_EAGER_ATTN = "eager"

_loaded_models: dict[str, Any] = {}  # hf_model_id -> nnsight LanguageModel, kept warm


def get_loaded_model_id() -> str | None:
    if not _loaded_models:
        return None
    return next(iter(_loaded_models))


def _load_model(hf_model_id: str):
    """Load (or return the already-warm) nnsight-wrapped model. Only one
    model is kept warm at a time — loading a second evicts the first, since
    this service assumes one GPU and multi-GB-per-model residency."""
    if hf_model_id in _loaded_models:
        return _loaded_models[hf_model_id]

    _loaded_models.clear()  # evict whatever was warm before

    from nnsight import LanguageModel

    logger.info("Loading %s (attn_implementation=eager, this may take a while)...", hf_model_id)
    t0 = time.time()
    model = LanguageModel(
        hf_model_id,
        device_map="auto",
        dispatch=True,
        attn_implementation=_EAGER_ATTN,
    )
    logger.info("Loaded %s in %.1fs", hf_model_id, time.time() - t0)
    _loaded_models[hf_model_id] = model
    return model


def _resolve_layers(model) -> list:
    """Return the decoder layer list for standard LlamaForCausalLM-style
    architectures. Raises AttributeError (surfaced to the caller as a clean
    failure) for architectures with a different module tree."""
    return model.model.layers


def run_capture(
    hf_model_id: str,
    prompt: str,
    layers: list[int] | None,
    capture_attention: bool,
    capture_residual: bool,
    logit_lens_topk: int,
    max_seq_len: int,
) -> dict:
    """Synchronous capture pass — called from a background thread by the
    service's job runner (main.py), since this blocks on GPU compute and
    nnsight's trace() API is not natively async.

    Returns a dict shaped for InspectionRun.summary_json on the main
    backend's side: {per_layer: [...], token_count, truncated, full_tensors:
    {layer_idx: {...}}} — full_tensors only populated for explicitly
    requested layers (see docstring on data-volume control in the plan).
    """
    model = _load_model(hf_model_id)
    all_layers = _resolve_layers(model)
    num_layers = len(all_layers)
    target_layers = layers if layers else list(range(num_layers))
    target_layers = [l for l in target_layers if 0 <= l < num_layers]

    tokenized = model.tokenizer(prompt, return_tensors="pt")
    token_count = tokenized["input_ids"].shape[-1]
    truncated = token_count > max_seq_len
    if truncated:
        prompt_for_capture = model.tokenizer.decode(tokenized["input_ids"][0][:max_seq_len])
    else:
        prompt_for_capture = prompt

    per_layer: list[dict] = []
    full_tensors: dict[int, dict] = {}

    with model.trace() as tracer:
        with tracer.invoke(prompt_for_capture):
            saved_residuals: dict[int, Any] = {}
            saved_attn: dict[int, Any] = {}

            for layer_idx in target_layers:
                layer = all_layers[layer_idx]
                if capture_residual:
                    saved_residuals[layer_idx] = layer.output[0].save()
                if capture_attention:
                    # Attention module's output tuple: (hidden_states, attn_weights, ...)
                    # attn_weights is index 1 when output_attentions-equivalent capture
                    # is active under eager attention.
                    saved_attn[layer_idx] = layer.self_attn.output[1].save()

    # Logit lens: apply the model's own final norm + lm_head to each saved
    # residual-stream snapshot, outside the trace context (plain tensor ops
    # on the now-materialized .value tensors) — mirrors nnsight's own
    # documented logit-lens tutorial pattern (model.lm_head(model.norm(x))),
    # just run post-trace since we already have concrete tensors here.
    for layer_idx in target_layers:
        entry: dict = {"layer": layer_idx}

        if capture_residual and layer_idx in saved_residuals:
            residual = saved_residuals[layer_idx].value
            entry["residual_norm"] = float(residual.norm(dim=-1).mean().item())

            with torch.no_grad():
                normed = model.model.norm(residual)
                logits = model.lm_head(normed)
                probs = torch.softmax(logits[0, -1], dim=-1)  # last token position
                topk = torch.topk(probs, k=min(logit_lens_topk, probs.shape[-1]))
                entry["logit_lens_top_tokens"] = [
                    {"token": model.tokenizer.decode([tid]), "probability": float(p)}
                    for p, tid in zip(topk.values.tolist(), topk.indices.tolist())
                ]

            if layer_idx in (layers or []):
                full_tensors.setdefault(layer_idx, {})["residual"] = residual.detach().cpu()

        if capture_attention and layer_idx in saved_attn:
            attn = saved_attn[layer_idx].value  # [batch, num_heads, seq, seq]
            num_heads = attn.shape[1]
            # Per-head attention entropy — low entropy = concentrated/committed
            # attention (often meaningful, e.g. induction/copy behavior), high
            # entropy = diffuse (often uninterpretable). Standard practitioner
            # signal, not a raw heatmap dump — see the plan's framing.
            probs_per_head = attn[0]  # [num_heads, seq, seq]
            eps = 1e-12
            entropy = -(probs_per_head * (probs_per_head + eps).log()).sum(dim=-1).mean(dim=-1)
            entry["attention_entropy_by_head"] = [float(e) for e in entropy.tolist()]
            entry["num_heads"] = num_heads

            if layer_idx in (layers or []):
                full_tensors.setdefault(layer_idx, {})["attention"] = attn.detach().cpu()

        per_layer.append(entry)

    return {
        "token_count": token_count,
        "truncated": truncated,
        "per_layer": per_layer,
        "_full_tensors": full_tensors,  # consumed by the job runner to write a safetensors artifact, not sent as JSON
    }
