import tempfile
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.toolpath_engine import evaluate_fileobj, evaluate_gcode
from api.toolpath_engine.job_manager import get_job, register_source, start_job
from api.toolpath_engine.rule_config import load_rule_config


router = APIRouter(prefix="/toolpath", tags=["toolpath"])


class IssueV2(BaseModel):
    code: str
    title: str
    description: str
    severity: str
    category: str
    dimension: str
    line_range: Optional[List[int]] = None
    segment_range: Optional[List[str]] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    suggestion: str = ""


class EvaluationResponseV2(BaseModel):
    final_conclusion: str
    allow_continue: bool
    summary: str
    total_score: float
    dimension_scores: Dict[str, float]
    issue_counts: Dict[str, int]
    issues: List[IssueV2]
    artifacts: Dict[str, str]
    metrics: Dict[str, Any]
    task_meta: Dict[str, Any]


class JobStartResponse(BaseModel):
    job_id: str
    file_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    file_id: str
    status: str
    mode: str
    progress: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    result: Optional[EvaluationResponseV2] = None


def _decode_upload_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded.strip():
            return decoded
    return data.decode("utf-8", errors="ignore")


def _result_to_response_v2(result) -> EvaluationResponseV2:
    issues: List[IssueV2] = []
    for it in result.issues:
        issues.append(
            IssueV2(
                code=it.code,
                title=it.title,
                description=it.description,
                severity=it.severity.value,
                category=it.category,
                dimension=it.dimension,
                line_range=list(it.line_range) if it.line_range else None,
                segment_range=list(it.segment_range) if it.segment_range else None,
                evidence=it.evidence,
                suggestion=it.suggestion,
            )
        )

    return EvaluationResponseV2(
        final_conclusion=result.final_conclusion.value,
        allow_continue=result.allow_continue,
        summary=result.summary,
        total_score=result.total_score,
        dimension_scores=result.dimension_scores,
        issue_counts=result.issue_counts,
        issues=issues,
        artifacts=result.artifacts,
        metrics=result.metrics,
        task_meta=result.task_meta,
    )


async def _store_upload(upload: UploadFile, *, max_bytes: int) -> str:
    store_dir = tempfile.gettempdir()
    path = f"{store_dir}/skera_toolpath_jobs/{uuid.uuid4().hex}_{upload.filename or 'toolpath.nc'}"
    total = 0
    try:
        import os

        os.makedirs(f"{store_dir}/skera_toolpath_jobs", exist_ok=True)
        with open(path, "wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"文件过大({total}B)，超过限制({max_bytes}B)")
                out.write(chunk)
    finally:
        try:
            await upload.close()
        except Exception:
            pass
    return register_source(path=path, filename=upload.filename or "", size_bytes=total)


def _store_text(text: str) -> str:
    store_dir = tempfile.gettempdir()
    import os

    os.makedirs(f"{store_dir}/skera_toolpath_jobs", exist_ok=True)
    raw = text.encode("utf-8")
    path = f"{store_dir}/skera_toolpath_jobs/{uuid.uuid4().hex}_inline.gcode"
    with open(path, "wb") as out:
        out.write(raw)
    return register_source(path=path, filename="inline.gcode", size_bytes=len(raw))


@router.post("/evaluate", response_model=EvaluationResponseV2)
async def evaluate_toolpath(
    file: Optional[UploadFile] = File(default=None),
    gcode_text: str = Form(default=""),
    software_source: str = Form(default=""),
    machine_model: str = Form(default=""),
):
    source = gcode_text or ""
    filename = ""
    result = None
    if file is not None:
        filename = file.filename or ""
        try:
            raw_cfg = load_rule_config()
            max_file_bytes = int((raw_cfg.get("analysis_limits", {}) or {}).get("max_file_bytes", 157286400))
        except Exception:
            max_file_bytes = 157286400

        try:
            file.file.seek(0, 2)
            size = int(file.file.tell())
            file.file.seek(0)
        except Exception:
            size = -1

        if size > max_file_bytes:
            raise HTTPException(status_code=413, detail=f"文件过大({size}B)，超过限制({max_file_bytes}B)")
        if size == 0 and not source.strip():
            raise HTTPException(status_code=400, detail="请上传刀路文件或输入 G 代码文本")

        if size >= 8 * 1024 * 1024 or not source.strip():
            try:
                result = await run_in_threadpool(
                    evaluate_fileobj,
                    file.file,
                    file_name=filename,
                    software_source=software_source,
                    machine_model=machine_model,
                )
            except TimeoutError:
                raise HTTPException(status_code=408, detail="评测超时，请降低文件大小或启用分段评测") from None
        else:
            data = await file.read()
            file_source = _decode_upload_bytes(data)
            source = file_source if file_source.strip() else source

    if file is None and not source.strip():
        raise HTTPException(status_code=400, detail="请上传刀路文件或输入 G 代码文本")

    if result is None:
        result = evaluate_gcode(
            source,
            file_name=filename,
            software_source=software_source,
            machine_model=machine_model,
        )

    return _result_to_response_v2(result)


@router.post("/evaluate_job", response_model=JobStartResponse)
async def evaluate_toolpath_job(
    file: Optional[UploadFile] = File(default=None),
    file_id: str = Form(default=""),
    gcode_text: str = Form(default=""),
    software_source: str = Form(default=""),
    machine_model: str = Form(default=""),
    mode: str = Form(default="sample"),
    sample_lines: int = Form(default=50000),
):
    try:
        raw_cfg = load_rule_config()
        max_file_bytes = int((raw_cfg.get("analysis_limits", {}) or {}).get("max_file_bytes", 157286400))
    except Exception:
        max_file_bytes = 157286400

    mode_norm = (mode or "sample").strip().lower()
    if mode_norm not in {"sample", "full"}:
        raise HTTPException(status_code=400, detail="mode 必须为 sample 或 full")

    src_file_id = (file_id or "").strip()
    if not src_file_id:
        if file is not None:
            src_file_id = await _store_upload(file, max_bytes=max_file_bytes)
        else:
            text = (gcode_text or "").strip()
            if not text:
                raise HTTPException(status_code=400, detail="请上传刀路文件或输入 G 代码文本")
            if len(text.encode("utf-8")) > max_file_bytes:
                raise HTTPException(status_code=413, detail=f"文本过大，超过限制({max_file_bytes}B)")
            src_file_id = _store_text(text)

    try:
        job_id = start_job(
            file_id=src_file_id,
            mode=mode_norm,
            sample_lines=int(sample_lines) if mode_norm == "sample" else None,
            software_source=software_source,
            machine_model=machine_model,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="file_id 不存在或已过期") from None

    return JobStartResponse(job_id=job_id, file_id=src_file_id, status="queued")


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_toolpath_job(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 不存在或已过期")
    return JobStatusResponse(
        job_id=job.job_id,
        file_id=job.file_id,
        status=job.status,
        mode=job.mode,
        progress=job.progress,
        error=job.error,
        result=_result_to_response_v2(job.result) if job.status == "done" and job.result is not None else None,
    )
