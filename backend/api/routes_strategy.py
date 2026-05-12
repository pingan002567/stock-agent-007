from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import StrategySpec, model_to_dict

router = APIRouter(tags=["strategies"])


@router.get("/api/strategies")
def list_strategies(request: Request, services: AppServices = Depends(get_services)):
    return {"items": [model_to_dict(item) for item in services.strategy_service.list_strategies()]}


@router.post("/api/strategies")
def create_strategy(payload: StrategySpec, request: Request, services: AppServices = Depends(get_services)):
    try:
        strategy = services.strategy_service.create_strategy(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return model_to_dict(strategy)


@router.get("/api/strategies/{strategy_id}")
def get_strategy(strategy_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.strategy_service.get_strategy(strategy_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="strategy not found") from exc


@router.put("/api/strategies/{strategy_id}")
def update_strategy(strategy_id: str, payload: StrategySpec, request: Request, services: AppServices = Depends(get_services)):
    try:
        strategy = services.strategy_service.update_strategy(strategy_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="strategy not found") from exc
    return model_to_dict(strategy)


@router.delete("/api/strategies/{strategy_id}")
def delete_strategy(strategy_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        deleted = services.strategy_service.delete_strategy(strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="strategy not found") from exc
    return {"deleted": deleted, "strategy_id": strategy_id}


@router.post("/api/strategies/{strategy_id}/backtest")
def backtest_strategy(
    strategy_id: str,
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    services: AppServices = Depends(get_services),
):
    body = payload or {}
    try:
        run = services.strategy_service.run_backtest(
            strategy_id,
            period=body.get("period"),
            universe=body.get("universe"),
            parameters=body.get("parameters"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="strategy not found") from exc
    return model_to_dict(run)


@router.get("/api/strategies/{strategy_id}/backtests")
def list_backtests(strategy_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        items = services.strategy_service.list_backtests(strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="strategy not found") from exc
    return {"items": [model_to_dict(item) for item in items]}


@router.get("/api/strategies/{strategy_id}/backtests/latest")
def get_latest_backtest(strategy_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        items = services.strategy_service.list_backtests(strategy_id, limit=1)
        if not items:
            raise HTTPException(status_code=404, detail="no backtests found")
        return model_to_dict(items[0])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="strategy not found") from exc


@router.get("/api/backtests/{run_id}")
def get_backtest(run_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.strategy_service.get_backtest(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="backtest not found") from exc
