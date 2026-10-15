from __future__ import annotations

from fastapi import Request

from backend.bootstrap import AppServices


def get_services(request: Request) -> AppServices:
    return request.app.state.services
