from __future__ import annotations

from backend.schemas import AuthorityLevel


ORDER = [AuthorityLevel.A1, AuthorityLevel.A2, AuthorityLevel.A3, AuthorityLevel.A4, AuthorityLevel.A5]


class PermissionDenied(Exception):
    pass


class PermissionGuard:
    def require(self, current: AuthorityLevel, required: AuthorityLevel, action: str) -> None:
        if ORDER.index(current) < ORDER.index(required):
            raise PermissionDenied(f"{action} requires {required.value}, current={current.value}")

    def block_real_order(self) -> None:
        raise PermissionDenied("real order execution is disabled in V1")
