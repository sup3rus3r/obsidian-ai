# Obsidian AI Finetune Service

Standalone LoRA/QLoRA fine-tuning service — the `local_wsl2` compute backend
for the platform's fine-tuning feature. Deliberately isolated from the main
backend: its own venv, own dependencies (torch, peft, trl, bitsandbytes),
own GPU memory footprint. The main backend never imports this service's
code; it only talks to it over HTTP, and only if you start it yourself.

## What this is (and isn't)

A real LoRA training loop (via `trl.SFTTrainer`) and, optionally, a
merge -> GGUF conversion -> quantization -> Ollama registration pipeline.
This is a *local, single-GPU, single-job-at-a-time* service — it holds no
queueing or multi-tenant guarantees. Treat it like you'd treat a locally
run Ollama instance: one box, one job, start it and leave it running.

## Setup (inside WSL2)

This service must run inside a CUDA-enabled WSL2 distro — training with
bitsandbytes 4-bit/8-bit quantization and GPU-accelerated attention needs
real CUDA, which plain Windows-hosted Python cannot give you reliably.

1. Install a CUDA-enabled WSL2 distro (Ubuntu 22.04+ recommended) and
   confirm `nvidia-smi` works inside it (NVIDIA's WSL2 CUDA driver, not a
   separate in-distro driver install).
2. `cd backend/finetune_service && uv sync` — pulls the CUDA build of
   torch via the pinned index in `pyproject.toml`.
3. Build `llama.cpp` inside the same WSL2 distro (needed for GGUF export):
   ```bash
   git clone https://github.com/ggerganov/llama.cpp
   cd llama.cpp && make LLAMA_CUDA=1
   ```
   Set `LLAMACPP_DIR` to point at this checkout (used to locate
   `convert_hf_to_gguf.py` and the `llama-quantize` binary).
4. Install Ollama inside the same WSL2 distro
   (`curl -fsSL https://ollama.com/install.sh | sh`) — GGUF export's final
   step runs `ollama create` against this same distro's Ollama install, so
   it must be the same install the main backend will eventually point a
   new `ollama` LLMProvider at.

## Running

```bash
cd backend/finetune_service
uv run uvicorn app.main:app --host 0.0.0.0 --port 8766
```

This starts the service on `http://localhost:8766` (the main backend's
default `FINETUNE_SERVICE_URL`). **The main backend never starts this for
you — start it yourself inside WSL2 and leave it running, the same way you
run Ollama.** The main backend only checks whether it's reachable
(`GET /finetune/status`, which pings this service's `/health`).

## API

- `GET /health` — reachability, GPU availability, free VRAM.
- `POST /finetune` — `{base_hf_model_id, dataset_jsonl_b64, hyperparams}` -> `{job_id}`.
- `GET /finetune/{job_id}` — poll training status/progress.
- `POST /finetune/{job_id}/cancel` — best-effort cancel (checked between training steps).
- `GET /finetune/{job_id}/artifact` — download the zipped LoRA adapter.
- `POST /finetune/{job_id}/export` — `{quantization}` -> `{export_id}`: merge -> GGUF -> quantize -> `ollama create`.
- `GET /finetune/export/{export_id}` — poll export status.
- `GET /finetune/export/{export_id}/artifact` — download the quantized GGUF.

No auth beyond trusting localhost — don't expose this port to the network.
