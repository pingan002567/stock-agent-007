from __future__ import annotations

from typing import List

from backend.schemas import now_iso


class DevicesRepoMixin:
    def upsert_apns_device(
        self,
        *,
        device_token: str,
        environment: str,
        platform: str = "ios",
        bundle_id: str = "com.stockagent.app",
    ) -> dict:
        token = device_token.strip().lower()
        env = (environment or "sandbox").strip().lower()
        if env not in {"sandbox", "production"}:
            env = "sandbox"
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO apns_device(device_token, environment, platform, bundle_id, updated_at, created_at)
                VALUES (?, ?, ?, ?, ?, COALESCE(
                    (SELECT created_at FROM apns_device WHERE device_token = ?),
                    ?
                ))
                ON CONFLICT(device_token) DO UPDATE SET
                  environment=excluded.environment,
                  platform=excluded.platform,
                  bundle_id=excluded.bundle_id,
                  updated_at=excluded.updated_at
                """,
                (token, env, platform, bundle_id, now_iso(), token, now_iso()),
            )
            self.conn.commit()
        return {
            "device_token": token,
            "environment": env,
            "platform": platform,
            "bundle_id": bundle_id,
        }

    def delete_apns_device(self, device_token: str) -> bool:
        token = device_token.strip().lower()
        with self._lock:
            cur = self.conn.execute("DELETE FROM apns_device WHERE device_token = ?", (token,))
            self.conn.commit()
            return cur.rowcount > 0

    def list_apns_devices(self) -> List[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT device_token, environment, platform, bundle_id, updated_at, created_at FROM apns_device ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                "device_token": r[0],
                "environment": r[1],
                "platform": r[2],
                "bundle_id": r[3],
                "updated_at": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
