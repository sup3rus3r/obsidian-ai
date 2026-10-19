"""In-memory job store, shared by trainer.py (training jobs) and
gguf_pipeline.py (export jobs) — both are just string-keyed dicts, so one
generic store covers both job kinds."""

import uuid

_jobs: dict[str, dict] = {}


def create_job() -> str:
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "pending"}
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def update_job(job_id: str, **fields) -> None:
    if job_id not in _jobs:
        _jobs[job_id] = {}
    _jobs[job_id].update(fields)
