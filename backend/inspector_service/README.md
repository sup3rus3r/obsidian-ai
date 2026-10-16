# Obsidian AI Inspector Service

Standalone local-model interpretability inspection service — phase 2 of the
platform's model auditing feature. Deliberately isolated from the main
backend: its own venv, own dependencies (torch, nnsight), own GPU memory
footprint. The main backend never imports this service's code; it only
talks to it over HTTP, and only if you start it yourself.

## What this is (and isn't)

Real inspection of a local model's internals — attention patterns,
per-layer activations, logit-lens probing of what the model "would have
said" at each layer. This is **not** solved interpretability: a single
prompt's run shows *a* pattern for *that* input, not a validated general
claim about the model, and none of these techniques license claims about
what a model "believes," "knows," or "intends." See the main backend's
`inspector_engine.py` and the Inspector page's limits banner for the full
framing.

Only works for models whose real HuggingFace weights you can load — not
anything served purely through a cloud API (OpenAI/Anthropic/Google/etc.),
since those weights never leave the provider's servers.

## Setup

```bash
cd backend/inspector_service
uv sync
```

You'll also need the CUDA build of torch if you have an NVIDIA GPU (the
`pyproject.toml` already pins `torch==2.6.0+cu124` via the same index the
main backend uses) — see the main backend's README for the CUDA PyTorch
install notes if `uv sync` alone doesn't get you a working GPU build.

## Running

```bash
uv run uvicorn app.main:app --port 8765
```

This starts the service on `http://localhost:8765` (the main backend's
default `INSPECTOR_SERVICE_URL`). It stays running like you'd run Ollama —
**the main backend does not start or stop this process for you.** It only
checks whether it's reachable (`GET /inspector/status` on the main
backend, which pings this service's `/health`).

The first inspection request for a given model will take a while (loading
the HF checkpoint, forced to `attn_implementation="eager"` so attention
weights are actually extractable — SDPA/Flash Attention never materialize
the full attention matrix). The model stays warm in memory after that,
until a different model is requested (only one model is kept loaded at a
time).

## API

- `GET /health` — reachability + currently loaded model.
- `POST /inspect` — `{hf_model_id, prompt, capture_config}` → `{job_id, status}`.
- `GET /inspect/{job_id}` — poll for status/summary.
- `GET /inspect/{job_id}/artifact` — download the raw safetensors blob, if any full-resolution layers were requested.
- `POST /inspect/{job_id}/cancel` — best-effort cancel.

No auth beyond trusting localhost — treat this the same way you'd treat a
locally-run Ollama instance: don't expose this port to the network.
