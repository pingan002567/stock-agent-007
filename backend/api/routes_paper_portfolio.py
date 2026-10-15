from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import model_to_dict

router = APIRouter(prefix="/api/paper-portfolio", tags=["paper-portfolio"])


@router.get("")
def get_paper_portfolio(request: Request, services: AppServices = Depends(get_services)):
    projection = services.paper_portfolio_service.get_projection()
    return {
        "summary": services.paper_portfolio_service.get_summary(projection),
        "projection": model_to_dict(projection),
    }


@router.get("/positions")
def get_paper_portfolio_positions(request: Request, services: AppServices = Depends(get_services)):
    projection = services.paper_portfolio_service.get_projection()
    return {
        "baseline_id": projection.baseline_id,
        "as_of": projection.as_of,
        "degraded": projection.degraded,
        "items": [model_to_dict(item) for item in projection.positions],
        "warnings": [model_to_dict(item) for item in projection.warnings],
    }


@router.get("/performance")
def get_paper_portfolio_performance(request: Request, services: AppServices = Depends(get_services)):
    return services.paper_portfolio_service.get_performance()


@router.post("/snapshots")
def create_paper_portfolio_snapshot(request: Request, services: AppServices = Depends(get_services)):
    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="http")
    return model_to_dict(snapshot)


@router.get("/snapshots")
def list_paper_portfolio_snapshots(
    request: Request,
    limit: int = 50,
    services: AppServices = Depends(get_services),
):
    items = services.paper_portfolio_service.list_snapshots(limit=limit)
    return {"items": [model_to_dict(item) for item in items]}


@router.get("/snapshots/{snapshot_id}")
def get_paper_portfolio_snapshot(snapshot_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        snapshot = services.paper_portfolio_service.get_snapshot(snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="paper portfolio snapshot not found") from exc
    return model_to_dict(snapshot)
