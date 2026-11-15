"""SQLite store (SPEC §3): one connection, WAL, a lock around writes, domain models out."""

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .domain import (
    ACTIVE_CALL,
    BridgeDevice,
    Call,
    ContextItem,
    Follow,
    Moment,
    Pass,
    Segment,
    Skill,
    User,
    now,
)

M = TypeVar("M", bound=BaseModel)

# table -> (model, primary key columns, JSON columns)
TABLES: dict[str, tuple[type[BaseModel], tuple[str, ...], tuple[str, ...]]] = {
    "users": (User, ("id",), ("links", "portrait", "kinds_off", "expertise", "worth_knowing",
                              "portrait_colors")),
    "context_items": (ContextItem, ("id",), ()),
    "skills": (Skill, ("id",), ()),
    "follows": (Follow, ("follower_id", "expert_id"), ()),
    "calls": (Call, ("id",), ()),
    "devices": (BridgeDevice, ("id",), ("last_state",)),
    "segments": (Segment, ("id",), ()),
    "moments": (Moment, ("id",), ("body", "segment_ids")),
    "passes": (Pass, ("id",), ()),
}

INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS users_phone ON users(phone)",
    "CREATE INDEX IF NOT EXISTS ctx_user ON context_items(user_id)",
    "CREATE INDEX IF NOT EXISTS skills_owner ON skills(owner_id)",
    "CREATE INDEX IF NOT EXISTS calls_user ON calls(user_id)",
    "CREATE INDEX IF NOT EXISTS events_user ON events(user_id, kind, at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS devices_band ON devices(band)",
    "CREATE UNIQUE INDEX IF NOT EXISTS devices_token ON devices(token_sha256)",
    "CREATE INDEX IF NOT EXISTS segments_device ON segments(device_id, started_at)",
    "CREATE INDEX IF NOT EXISTS moments_user ON moments(user_id, started_at)",
]


def _enc(v: Any) -> Any:
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, datetime):
        return _ts(v)
    return v


def _ts(dt: datetime) -> str:
    """Fixed-width UTC text, so SQL string comparison is time order."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=OFF")
        with self.lock:
            for table, (model, pk, _) in TABLES.items():
                cols = ", ".join(model.model_fields)
                self.db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ({cols}, PRIMARY KEY ({', '.join(pk)}))"
                )
                # a column added to the model since the database was made (no data lost)
                have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
                for col in model.model_fields:
                    if col not in have:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
            self.db.execute("CREATE TABLE IF NOT EXISTS events (user_id, kind, at)")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS stripe_events (id PRIMARY KEY, at)"
            )
            for sql in INDEXES:
                self.db.execute(sql)

    def close(self) -> None:
        self.db.close()

    # ---- generic ---------------------------------------------------------------------------

    def _row(self, table: str, row: sqlite3.Row | None) -> Any:
        if row is None:
            return None
        model, _, json_cols = TABLES[table]
        d = {k: v for k, v in dict(row).items() if v is not None}   # NULL → the model default
        for c in json_cols:
            if d.get(c) is not None:
                d[c] = json.loads(d[c])
        return model.model_validate(d)

    def insert(self, table: str, obj: M) -> M:
        data = obj.model_dump()
        cols = list(data)
        with self.lock:
            self.db.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [_enc(_jsonable(data[c])) for c in cols],
            )
        return obj

    def update(self, table: str, id: str, **fields: Any) -> None:
        if not fields:
            return
        model = TABLES[table][0]
        unknown = set(fields) - set(model.model_fields)
        if unknown:
            raise KeyError(f"unknown fields {sorted(unknown)}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.lock:
            self.db.execute(
                f"UPDATE {table} SET {sets} WHERE id = ?",
                [_enc(_jsonable(v)) for v in fields.values()] + [id],
            )

    def get(self, table: str, id: str) -> Any:
        return self._row(table, self.db.execute(f"SELECT * FROM {table} WHERE id = ?", [id])
                         .fetchone())

    def select(self, table: str, where: str = "1", params: list | tuple = (),
               order: str = "", limit: int | None = None) -> list:
        sql = f"SELECT * FROM {table} WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._row(table, r) for r in self.db.execute(sql, list(params)).fetchall()]

    # ---- users -----------------------------------------------------------------------------

    def add_user(self, user: User) -> User:
        return self.insert("users", user)

    def get_user(self, user_id: str) -> User | None:
        return self.get("users", user_id)

    def user_by_phone(self, phone: str) -> User | None:
        rows = self.select("users", "phone = ?", [phone])
        return rows[0] if rows else None

    def update_user(self, user_id: str, **fields: Any) -> User | None:
        self.update("users", user_id, **fields)
        return self.get_user(user_id)

    def delete_user(self, user_id: str) -> None:
        """Remove the user and every row that references them, in one transaction."""
        with self.lock:
            dev_ids = [r[0] for r in self.db.execute(
                "SELECT id FROM devices WHERE user_id = ?", [user_id])]
            skill_ids = [r[0] for r in self.db.execute(
                "SELECT id FROM skills WHERE owner_id = ?", [user_id])]
            self.db.execute("BEGIN")
            try:
                for sql in (
                    "DELETE FROM skills WHERE owner_id = ?",
                    "DELETE FROM follows WHERE follower_id = ? OR expert_id = ?",
                    "DELETE FROM calls WHERE user_id = ?",
                    "DELETE FROM context_items WHERE user_id = ?",
                    "DELETE FROM events WHERE user_id = ?",
                    "DELETE FROM segments WHERE user_id = ?",
                    "DELETE FROM moments WHERE user_id = ?",
                    "DELETE FROM devices WHERE user_id = ?",
                    "DELETE FROM passes WHERE giver_id = ? OR receiver_id = ?",
                    "DELETE FROM users WHERE id = ?",
                ):
                    self.db.execute(sql, [user_id] * sql.count("?"))
                for sid in skill_ids:
                    self.db.execute("DELETE FROM passes WHERE skill_id = ?", [sid])
                for did in dev_ids:
                    self.db.execute("DELETE FROM segments WHERE device_id = ?", [did])
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def people(self, limit: int = 50) -> list[tuple[User, int]]:
        rows = self.db.execute(
            "SELECT owner_id, COUNT(*) n FROM skills WHERE status = 'published' "
            "GROUP BY owner_id ORDER BY n DESC LIMIT ?", [limit]).fetchall()
        out = []
        for r in rows:
            u = self.get_user(r["owner_id"])
            if u:
                out.append((u, r["n"]))
        return out

    # ---- context ---------------------------------------------------------------------------

    def add_context_items(self, items: list[ContextItem]) -> list[ContextItem]:
        for it in items:
            self.insert("context_items", it)
        return items

    def context_for(self, user_id: str) -> list[ContextItem]:
        return self.select("context_items", "user_id = ? AND status != 'removed'", [user_id],
                           order="rowid")

    def kept_context(self, user_id: str) -> list[ContextItem]:
        return self.select("context_items", "user_id = ? AND status = 'kept'", [user_id],
                           order="rowid")

    # ---- skills ----------------------------------------------------------------------------

    def add_skill(self, skill: Skill) -> Skill:
        return self.insert("skills", skill)

    def get_skill(self, skill_id: str) -> Skill | None:
        return self.get("skills", skill_id)

    def update_skill(self, skill_id: str, **fields: Any) -> Skill | None:
        self.update("skills", skill_id, **fields)
        return self.get_skill(skill_id)

    def skills_mine(self, owner_id: str) -> list[Skill]:
        return self.select("skills", "owner_id = ? AND status != 'removed'", [owner_id],
                           order="created_at DESC")

    def published_skills(self, owner_id: str) -> list[Skill]:
        return self.select("skills", "owner_id = ? AND status = 'published'", [owner_id],
                           order="created_at DESC")

    def count_published(self, owner_id: str) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM skills WHERE owner_id = ? AND status = 'published'",
            [owner_id]).fetchone()[0]

    def skills_from_call(self, call_id: str) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM skills WHERE call_id = ? AND status != 'removed'",
            [call_id]).fetchone()[0]

    # ---- follows ---------------------------------------------------------------------------

    def get_follow(self, follower_id: str, expert_id: str) -> Follow | None:
        rows = self.select("follows", "follower_id = ? AND expert_id = ?",
                           [follower_id, expert_id])
        return rows[0] if rows else None

    def follow(self, follower_id: str, expert_id: str) -> Follow:
        f = self.get_follow(follower_id, expert_id)
        return f or self.insert("follows", Follow(follower_id=follower_id, expert_id=expert_id))

    def unfollow(self, follower_id: str, expert_id: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM follows WHERE follower_id = ? AND expert_id = ?",
                            [follower_id, expert_id])

    def set_follow_paid(self, follower_id: str, expert_id: str, session_id: str) -> None:
        self.follow(follower_id, expert_id)
        with self.lock:
            self.db.execute(
                "UPDATE follows SET paid = 1, stripe_session_id = ? "
                "WHERE follower_id = ? AND expert_id = ?", [session_id, follower_id, expert_id])

    def follower_count(self, expert_id: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM follows WHERE expert_id = ?",
                               [expert_id]).fetchone()[0]

    def following(self, follower_id: str) -> list[Follow]:
        return self.select("follows", "follower_id = ?", [follower_id])

    # ---- calls -----------------------------------------------------------------------------

    def add_call(self, call: Call) -> Call:
        return self.insert("calls", call)

    def get_call(self, call_id: str) -> Call | None:
        return self.get("calls", call_id)

    def call_by_vapi_id(self, vapi_call_id: str) -> Call | None:
        rows = self.select("calls", "vapi_call_id = ?", [vapi_call_id])
        return rows[0] if rows else None

    def update_call(self, call_id: str, **fields: Any) -> Call | None:
        self.update("calls", call_id, **fields)
        return self.get_call(call_id)

    def calls_for(self, user_id: str) -> list[Call]:
        return self.select("calls", "user_id = ?", [user_id], order="created_at DESC")

    def latest_call(self, user_id: str) -> Call | None:
        rows = self.select("calls", "user_id = ?", [user_id], order="created_at DESC", limit=1)
        return rows[0] if rows else None

    def active_call(self, user_id: str) -> Call | None:
        q = ", ".join("?" * len(ACTIVE_CALL))
        rows = self.select("calls", f"user_id = ? AND status IN ({q})", [user_id, *ACTIVE_CALL],
                           order="created_at DESC", limit=1)
        return rows[0] if rows else None

    # ---- rate-limit events -----------------------------------------------------------------

    def add_event(self, user_id: str, kind: str, at: datetime | None = None) -> None:
        with self.lock:
            self.db.execute("INSERT INTO events VALUES (?, ?, ?)",
                            [user_id, kind, _ts(at or now())])

    def count_events(self, user_id: str, kind: str, since: datetime) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM events WHERE user_id = ? AND kind = ? AND at >= ?",
            [user_id, kind, _ts(since)]).fetchone()[0]

    def allow(self, user_id: str, kind: str, limit: int, per: timedelta = timedelta(days=1)
              ) -> bool:
        """True (and records the event) if under `limit` events in the last `per`."""
        if self.count_events(user_id, kind, now() - per) >= limit:
            return False
        self.add_event(user_id, kind)
        return True

    def mark_stripe_event(self, event_id: str) -> bool:
        """True the first time an event id is seen, False after (idempotency)."""
        with self.lock:
            cur = self.db.execute("INSERT OR IGNORE INTO stripe_events VALUES (?, ?)",
                                  [event_id, _ts(now())])
        return cur.rowcount == 1

    # ---- band: devices, segments, moments, passes ------------------------------------------

    def add_device(self, dev: BridgeDevice) -> BridgeDevice:
        return self.insert("devices", dev)

    def device_for_user(self, user_id: str) -> BridgeDevice | None:
        rows = self.select("devices", "user_id = ?", [user_id], limit=1)
        return rows[0] if rows else None

    def device_by_band(self, band: int) -> BridgeDevice | None:
        rows = self.select("devices", "band = ?", [band], limit=1)
        return rows[0] if rows else None

    def device_by_token(self, token_sha256: str) -> BridgeDevice | None:
        rows = self.select("devices", "token_sha256 = ?", [token_sha256], limit=1)
        return rows[0] if rows else None

    def update_device(self, device_id: str, **fields: Any) -> BridgeDevice | None:
        self.update("devices", device_id, **fields)
        return self.get("devices", device_id)

    def delete_device(self, device_id: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM segments WHERE device_id = ?", [device_id])
            self.db.execute("DELETE FROM devices WHERE id = ?", [device_id])

    def add_segment(self, seg: Segment) -> Segment:
        return self.insert("segments", seg)

    def segments(self, device_id: str, since: datetime | None = None) -> list[Segment]:
        if since is None:
            return self.select("segments", "device_id = ?", [device_id], order="started_at")
        return self.select("segments", "device_id = ? AND ended_at >= ?",
                           [device_id, _ts(since)], order="started_at")

    def delete_segments_since(self, device_id: str, since: datetime) -> list[str]:
        ids = [s.id for s in self.segments(device_id, since)]
        with self.lock:
            self.db.execute("DELETE FROM segments WHERE device_id = ? AND ended_at >= ?",
                            [device_id, _ts(since)])
        return ids

    def segments_for_user(self, user_id: str, since: datetime) -> list[Segment]:
        return self.select("segments", "user_id = ? AND ended_at >= ?", [user_id, _ts(since)],
                           order="started_at")

    def delete_segments_for_user(self, user_id: str) -> int:
        with self.lock:
            return self.db.execute("DELETE FROM segments WHERE user_id = ?",
                                   [user_id]).rowcount

    def delete_segments_before(self, before: datetime) -> int:
        with self.lock:
            return self.db.execute("DELETE FROM segments WHERE ended_at < ?",
                                   [_ts(before)]).rowcount

    def add_moment(self, m: Moment) -> Moment:
        return self.insert("moments", m)

    def get_moment(self, moment_id: str) -> Moment | None:
        return self.get("moments", moment_id)

    def update_moment(self, moment_id: str, **fields: Any) -> Moment | None:
        self.update("moments", moment_id, **fields)
        return self.get_moment(moment_id)

    def moments_for(self, user_id: str, since: datetime | None = None,
                    kind: str | None = None) -> list[Moment]:
        where, params = "user_id = ?", [user_id]
        if since is not None:
            where += " AND ended_at >= ?"
            params.append(_ts(since))
        if kind is not None:
            where += " AND kind = ?"
            params.append(kind)
        return self.select("moments", where, params, order="started_at DESC")

    def delete_moment(self, moment_id: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM moments WHERE id = ?", [moment_id])

    def add_pass(self, p: Pass) -> Pass:
        return self.insert("passes", p)

    def passes_for(self, user_id: str) -> list[Pass]:
        return self.select("passes", "giver_id = ? OR receiver_id = ?", [user_id, user_id],
                           order="created_at DESC")

    def passes_for_skill(self, skill_id: str) -> list[Pass]:
        return self.select("passes", "skill_id = ?", [skill_id])

    def all_devices(self) -> list[BridgeDevice]:
        return self.select("devices")


def _jsonable(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return _jsonable(v.model_dump())
    if isinstance(v, datetime):
        return _ts(v)
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if hasattr(v, "unicode_string"):  # pydantic Url
        return str(v)
    return v
