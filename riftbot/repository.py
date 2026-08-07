from __future__ import annotations

import pickle
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import GeneratedDungeon, RiftListing, RiftStatus


ACTIVE_RIFT_STATUSES = (
    RiftStatus.AVAILABLE,
    RiftStatus.GENERATING,
    RiftStatus.READY,
    RiftStatus.ACTIVE,
)


def _load_rift(payload: bytes) -> RiftListing:
    """Load a Rift and migrate the former ownership object when present."""

    rift: RiftListing = pickle.loads(payload)
    if not hasattr(rift, "owner"):
        legacy = getattr(rift, "ownership", None)
        if legacy is None:
            rift.owner = "Independent"
        elif legacy.ownership_type.value == "council_assigned":
            rift.owner = "Council Assigned"
        elif legacy.ownership_type.value == "independent":
            rift.owner = "Independent"
        else:
            rift.owner = legacy.owner_name or "Independent"
        rift.ownership = None
    return rift


class RiftRepository:
    def __init__(self, path: str | Path = "riftbot.sqlite3") -> None:
        self.path = str(path)
        self.initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS rifts (
                    rift_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    claimed_by_user_id INTEGER,
                    claimed_at TEXT,
                    dungeon_id TEXT,
                    thread_id INTEGER,
                    payload BLOB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dungeons (
                    dungeon_id TEXT PRIMARY KEY,
                    rift_id TEXT NOT NULL UNIQUE,
                    payload BLOB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rift_id_sequence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                );
                """
            )
            columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(rifts)")
            }
            if "owner" not in columns:
                db.execute("ALTER TABLE rifts ADD COLUMN owner TEXT")

            # Backfill databases created before owner became queryable.
            rows = db.execute(
                "SELECT rift_id, payload FROM rifts WHERE owner IS NULL"
            ).fetchall()
            for row in rows:
                rift = _load_rift(row["payload"])
                db.execute(
                    "UPDATE rifts SET owner = ? WHERE rift_id = ?",
                    (rift.owner, row["rift_id"]),
                )

            db.execute("DROP INDEX IF EXISTS idx_rifts_status_owner")
            db.execute(
                """
                CREATE INDEX idx_rifts_status_owner
                ON rifts(status, owner COLLATE NOCASE)
                """
            )

    def save_rift(self, rift: RiftListing) -> None:
        with self.connection() as db:
            if rift.rift_id.startswith("pending:"):
                cursor = db.execute(
                    "INSERT INTO rift_id_sequence DEFAULT VALUES"
                )
                rift.rift_id = str(cursor.lastrowid)
            db.execute(
                """
                INSERT INTO rifts (
                    rift_id, status, owner, generated_at, expires_at,
                    claimed_by_user_id, claimed_at, dungeon_id,
                    thread_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rift_id) DO UPDATE SET
                    status=excluded.status,
                    owner=excluded.owner,
                    generated_at=excluded.generated_at,
                    expires_at=excluded.expires_at,
                    claimed_by_user_id=excluded.claimed_by_user_id,
                    claimed_at=excluded.claimed_at,
                    dungeon_id=excluded.dungeon_id,
                    thread_id=excluded.thread_id,
                    payload=excluded.payload
                """,
                (
                    rift.rift_id,
                    rift.status.value,
                    rift.owner,
                    rift.generated_at.isoformat(),
                    rift.expires_at.isoformat(),
                    rift.claimed_by_user_id,
                    rift.claimed_at.isoformat() if rift.claimed_at else None,
                    rift.dungeon_id,
                    rift.thread_id,
                    pickle.dumps(rift),
                ),
            )

    def has_generated_rifts_on(self, generated_date) -> bool:
        """Return whether a Rift batch is already stored for a UTC date."""

        with self.connection() as db:
            row = db.execute(
                """
                SELECT 1 FROM rifts
                WHERE generated_at >= ? AND generated_at < ?
                LIMIT 1
                """,
                (
                    f"{generated_date.isoformat()}T00:00:00",
                    f"{generated_date.isoformat()}T23:59:59.999999",
                ),
            ).fetchone()
        return row is not None

    def get_rift(self, rift_id: str) -> RiftListing | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM rifts WHERE rift_id = ?",
                (rift_id,),
            ).fetchone()
        return _load_rift(row["payload"]) if row else None

    def list_active_rifts(
        self,
        *,
        region: str | None = None,
        owner: str | None = None,
    ) -> list[RiftListing]:
        """Return active Rifts, optionally filtered by region or owner."""

        placeholders = ", ".join("?" for _ in ACTIVE_RIFT_STATUSES)
        conditions = [f"status IN ({placeholders})"]
        parameters: list[str] = [
            status.value for status in ACTIVE_RIFT_STATUSES
        ]

        if region is not None:
            conditions.append("owner = ? COLLATE NOCASE")
            parameters.append(region)
        if owner is not None:
            conditions.append("owner = ? COLLATE NOCASE")
            parameters.append(owner)

        with self.connection() as db:
            rows = db.execute(
                f"""
                SELECT payload FROM rifts
                WHERE {' AND '.join(conditions)}
                ORDER BY CAST(rift_id AS INTEGER)
                """,
                parameters,
            ).fetchall()

        listings = [_load_rift(row["payload"]) for row in rows]
        return listings

    def claim_available(self, rift_id: str, user_id: int) -> bool:
        claimed_at = datetime.now(timezone.utc)
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM rifts WHERE rift_id = ?",
                (rift_id,),
            ).fetchone()
            if not row:
                return False
            rift = _load_rift(row["payload"])
            if rift.status is not RiftStatus.AVAILABLE:
                return False

            rift.status = RiftStatus.GENERATING
            rift.claimed_by_user_id = user_id
            rift.claimed_at = claimed_at
            result = db.execute(
                """
                UPDATE rifts
                SET status=?, claimed_by_user_id=?, claimed_at=?, payload=?
                WHERE rift_id=? AND status=?
                """,
                (
                    RiftStatus.GENERATING.value,
                    user_id,
                    claimed_at.isoformat(),
                    pickle.dumps(rift),
                    rift_id,
                    RiftStatus.AVAILABLE.value,
                ),
            )
            return result.rowcount == 1

    def save_dungeon(self, dungeon: GeneratedDungeon) -> None:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO dungeons (dungeon_id, rift_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(rift_id) DO UPDATE SET
                    dungeon_id=excluded.dungeon_id,
                    payload=excluded.payload
                """,
                (
                    dungeon.dungeon_id,
                    dungeon.rift_id,
                    pickle.dumps(dungeon),
                ),
            )

    def get_dungeon_for_rift(self, rift_id: str) -> GeneratedDungeon | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM dungeons WHERE rift_id = ?",
                (rift_id,),
            ).fetchone()
        return pickle.loads(row["payload"]) if row else None

    def delete_dungeon_for_rift(self, rift_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM dungeons WHERE rift_id = ?", (rift_id,))

    def expire_available(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        expired: list[str] = []
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT rift_id, payload FROM rifts
                WHERE status = ? AND expires_at <= ?
                """,
                (RiftStatus.AVAILABLE.value, now.isoformat()),
            ).fetchall()
            for row in rows:
                rift = _load_rift(row["payload"])
                rift.status = RiftStatus.EXPIRED
                db.execute(
                    "UPDATE rifts SET status=?, payload=? WHERE rift_id=?",
                    (
                        RiftStatus.EXPIRED.value,
                        pickle.dumps(rift),
                        rift.rift_id,
                    ),
                )
                expired.append(rift.rift_id)
        return expired
