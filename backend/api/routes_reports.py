from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import ReportGenerateRequest, model_to_dict

router = APIRouter(prefix="/api/reports", tags=["reports"])
templates_router = APIRouter(prefix="/api/report-templates", tags=["reports"])


@templates_router.get("")
@router.get("/templates")
def list_report_templates(request: Request, services: AppServices = Depends(get_services)):
    return {"items": [model_to_dict(item) for item in services.report_service.list_templates()]}


@router.get("")
def list_reports(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    services: AppServices = Depends(get_services),
):
    all_items = services.report_service.list_reports()
    total = len(all_items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_items = all_items[start_idx:end_idx]
    return {
        "items": [model_to_dict(item) for item in paginated_items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/generate")
def generate_report(payload: ReportGenerateRequest, request: Request, services: AppServices = Depends(get_services)):
    try:
        report = services.report_service.generate(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404 if isinstance(exc, KeyError) else 400, detail=str(exc)) from exc
    return model_to_dict(report)


@router.get("/{report_id}")
def get_report(report_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        report = services.report_service.get_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found")
    return model_to_dict(report)


@router.get("/{report_id}/quality")
def get_report_quality(report_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return services.report_service.get_quality(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc


@router.post("/{report_id}/rerun-quality")
def rerun_report_quality(report_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return services.report_service.rerun_quality(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc


@router.get("/{report_id}/export")
def export_report(
    report_id: str,
    request: Request,
    format: str = Query("markdown", description="Export format: markdown or pdf"),
    services: AppServices = Depends(get_services),
):
    try:
        if format == "pdf":
            pdf_bytes = services.report_service.export_report_pdf(report_id)
            return StreamingResponse(
                BytesIO(pdf_bytes),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{report_id}.pdf"'},
            )
        result = services.report_service.export_report(report_id)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail=f"PDF export not available: missing dependency. Install with: uv sync --extra export",
        ) from exc
