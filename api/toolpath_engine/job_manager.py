from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .models import EvaluationResult
from .streaming import evaluate_fileobj


@dataclass(frozen=True)
class StoredSource:
    file_id: str
    path: str
    filename: str
    size_bytes: int
    created_at_s: float


@dataclass
class ToolpathJob:
    job_id: str
    file_id: str
    filename: str
    mode: str
    sample_lines: Optional[int]
    software_source: str
    machine_model: str
    status: str = "queued"
    progress: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    result: Optional[EvaluationResult] = None
    created_at_s: float = field(default_factory=lambda: time.time())
    started_at_s: float = 0.0
    finished_at_s: float = 0.0


_LOCK = threading.Lock()
_SOURCES: Dict[str, StoredSource] = {}
_JOBS: Dict[str, ToolpathJob] = {}

_STORE_DIR = Path(tempfile.gettempdir()) / "skera_toolpath_jobs"
_TTL_S = 24 * 3600


def _ensure_store_dir() -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_expired(*, now_s: Optional[float] = None) -> None:
    now = float(now_s if now_s is not None else time.time())
    with _LOCK:
        source_ids = list(_SOURCES.keys())
        job_ids = list(_JOBS.keys())

    for fid in source_ids:
        with _LOCK:
            src = _SOURCES.get(fid)
        if src is None:
            continue
        if now - src.created_at_s <= _TTL_S:
            continue
        try:
            os.remove(src.path)
        except Exception:
            pass
        with _LOCK:
            _SOURCES.pop(fid, None)

    for jid in job_ids:
        with _LOCK:
            job = _JOBS.get(jid)
        if job is None:
            continue
        if now - job.created_at_s <= _TTL_S:
            continue
        with _LOCK:
            _JOBS.pop(jid, None)


def register_source(*, path: str, filename: str, size_bytes: int) -> str:
    _ensure_store_dir()
    cleanup_expired()
    file_id = uuid.uuid4().hex
    src = StoredSource(
        file_id=file_id,
        path=str(path),
        filename=filename,
        size_bytes=int(size_bytes),
        created_at_s=time.time(),
    )
    with _LOCK:
        _SOURCES[file_id] = src
    return file_id


def get_source(file_id: str) -> Optional[StoredSource]:
    with _LOCK:
        return _SOURCES.get(file_id)


def start_job(
    *,
    file_id: str,
    mode: str,
    sample_lines: Optional[int],
    software_source: str,
    machine_model: str,
) -> str:
    cleanup_expired()
    src = get_source(file_id)
    if src is None:
        raise KeyError("source_not_found")

    job_id = uuid.uuid4().hex
    job = ToolpathJob(
        job_id=job_id,
        file_id=file_id,
        filename=src.filename,
        mode=mode,
        sample_lines=sample_lines,
        software_source=software_source,
        machine_model=machine_model,
        status="queued",
        progress={"percent": 0.0, "lines": 0, "bytes": 0, "total_bytes": src.size_bytes},
    )
    with _LOCK:
        _JOBS[job_id] = job

    t = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    t.start()
    return job_id


def get_job(job_id: str) -> Optional[ToolpathJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def _set_job_fields(job_id: str, updates: Dict[str, Any]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for k, v in updates.items():
            setattr(job, k, v)


def _update_job_progress(job_id: str, patch: Dict[str, Any]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.progress.update(patch)


def _run_job(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    src = get_source(job.file_id)
    if src is None:
        _set_job_fields(job_id, {"status": "error", "error": "source_not_found", "finished_at_s": time.time()})
        return

    _set_job_fields(job_id, {"status": "running", "started_at_s": time.time()})

    max_lines = int(job.sample_lines) if job.mode == "sample" and job.sample_lines is not None else None

    try:
        with open(src.path, "rb") as f:
            total_bytes = max(1, int(src.size_bytes))

            def on_progress(p: Dict[str, Any]) -> None:
                lines = int(p.get("lines", 0))
                try:
                    pos = int(f.tell())
                except Exception:
                    pos = 0
                if max_lines is not None and max_lines > 0:
                    percent = min(1.0, lines / float(max_lines))
                else:
                    percent = min(1.0, pos / float(total_bytes))
                _update_job_progress(
                    job_id,
                    {"lines": lines, "bytes": pos, "total_bytes": int(src.size_bytes), "percent": percent},
                )

            res = evaluate_fileobj(
                f,
                file_name=src.filename,
                software_source=job.software_source,
                machine_model=job.machine_model,
                max_lines=max_lines,
                on_progress=on_progress,
                progress_every=500 if max_lines is not None else 2000,
            )
        _set_job_fields(job_id, {"status": "done", "result": res, "finished_at_s": time.time()})
        _update_job_progress(job_id, {"percent": 1.0})
    except TimeoutError:
        _set_job_fields(job_id, {"status": "error", "error": "evaluation_timeout", "finished_at_s": time.time()})
    except Exception as e:
        _set_job_fields(job_id, {"status": "error", "error": str(e) or "unknown_error", "finished_at_s": time.time()})

