from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.toolpath_engine import evaluate_gcode


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


def _decode_upload_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded.strip():
            return decoded
    return data.decode("utf-8", errors="ignore")


@router.post("/evaluate", response_model=EvaluationResponseV2)
async def evaluate_toolpath(
    file: Optional[UploadFile] = File(default=None),
    gcode_text: str = Form(default=""),
    software_source: str = Form(default=""),
    machine_model: str = Form(default=""),
):
    source = gcode_text or ""
    filename = ""
    if file is not None:
        filename = file.filename or ""
        data = await file.read()
        file_source = _decode_upload_bytes(data)
        source = file_source if file_source.strip() else source

    if not source.strip():
        raise HTTPException(status_code=400, detail="请上传刀路文件或输入 G 代码文本")

    result = evaluate_gcode(
        source,
        file_name=filename,
        software_source=software_source,
        machine_model=machine_model,
    )

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
