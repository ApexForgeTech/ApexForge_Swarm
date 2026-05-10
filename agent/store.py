"""
Persistent SQLite storage for web sessions and multi-agent missions.
Thread-safe — all public methods acquire _lock before touching the DB.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """
    Web session + mission history, backed by SQLite.

    Tables:
        web_sessions  — WebSocket/API session message histories
        missions      — multi-agent mission records
    """

    def __init__(self, db_path: Path):
        self._db = str(db_path)
        self._lock = threading.RLock()
        self._init_schema()

    # ── Internal ───────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS web_sessions (
                    session_id TEXT PRIMARY KEY,
                    messages   TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    prompt     TEXT NOT NULL,
                    result     TEXT,
                    events     TEXT NOT NULL DEFAULT '[]',
                    status     TEXT NOT NULL DEFAULT 'running',
                    provider   TEXT,
                    model      TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_missions_created
                    ON missions (created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_sessions_updated
                    ON web_sessions (updated_at DESC);
            """)

    # ── Session API ────────────────────────────────────────────────────────

    def save_session(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        payload = json.dumps(messages, ensure_ascii=False)
        now = _now_iso()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO web_sessions (session_id, messages, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE
                SET messages = excluded.messages,
                    updated_at = excluded.updated_at
                """,
                (session_id, payload, now, now),
            )

    def load_session(self, session_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT messages FROM web_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return []
        try:
            return json.loads(row["messages"])
        except (json.JSONDecodeError, KeyError):
            return []

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                """
                SELECT session_id, created_at, updated_at,
                       json_array_length(messages) AS msg_count
                FROM web_sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM web_sessions WHERE session_id = ?",
                (session_id,),
            )
        return cur.rowcount > 0

    # ── Mission API ────────────────────────────────────────────────────────

    def create_mission(
        self,
        mission_id: str,
        prompt: str,
        provider: str = "",
        model: str = "",
    ) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO missions
                    (mission_id, prompt, events, status, provider, model, created_at)
                VALUES (?, ?, '[]', 'running', ?, ?, ?)
                """,
                (mission_id, prompt, provider, model, _now_iso()),
            )

    def append_mission_event(self, mission_id: str, event: Dict[str, Any]) -> None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT events FROM missions WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()
            if not row:
                return
            try:
                events: list = json.loads(row["events"])
            except (json.JSONDecodeError, KeyError):
                events = []
            events.append(event)
            conn.execute(
                "UPDATE missions SET events = ? WHERE mission_id = ?",
                (json.dumps(events, ensure_ascii=False), mission_id),
            )

    def finish_mission(
        self,
        mission_id: str,
        result: str,
        status: str = "completed",
    ) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                UPDATE missions
                SET result = ?, status = ?, finished_at = ?
                WHERE mission_id = ?
                """,
                (result, status, _now_iso(), mission_id),
            )

    def get_mission(self, mission_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["events"] = json.loads(data["events"])
        except (json.JSONDecodeError, KeyError):
            data["events"] = []
        return data

    def list_missions(
        self,
        limit: int = 50,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT mission_id, prompt, status, provider, model,
                           created_at, finished_at
                    FROM missions
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT mission_id, prompt, status, provider, model,
                           created_at, finished_at
                    FROM missions
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_mission(self, mission_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM missions WHERE mission_id = ?",
                (mission_id,),
            )
        return cur.rowcount > 0

    # ── Stats ──────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            session_count = conn.execute(
                "SELECT COUNT(*) FROM web_sessions"
            ).fetchone()[0]
            mission_rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM missions GROUP BY status"
            ).fetchall()
        mission_stats = {r["status"]: r["cnt"] for r in mission_rows}
        return {
            "session_count": session_count,
            "mission_count": sum(mission_stats.values()),
            "missions_by_status": mission_stats,
        }
