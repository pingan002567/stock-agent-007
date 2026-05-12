from __future__ import annotations

from uuid import uuid4

from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import AuditLog, AuthorityLevel


class AuditService:
    def __init__(self, repo: WorkbenchRepository) -> None:
        self.repo = repo

    def record(self, action: str, detail: str, authority_level: AuthorityLevel = AuthorityLevel.A1) -> AuditLog:
        log = AuditLog(
            audit_id=f"audit_{uuid4().hex[:10]}",
            action=action,
            detail=detail,
            authority_level=authority_level,
        )
        return self.repo.save_audit(log)
