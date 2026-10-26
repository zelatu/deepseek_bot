"""SQLite 存储层：对话原文 + 提炼出的事实。

设计原则：
- 原始对话永久保存，不删（删了就真失忆了）
- 事实用软删除（active=0），保留可追溯
- embedding 直接存 BLOB，不引入额外向量库
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "whale.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    user_id     TEXT,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    embedding   BLOB
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_key, id);

CREATE TABLE IF NOT EXISTS facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scope         TEXT NOT NULL,
    content       TEXT NOT NULL,
    category      TEXT DEFAULT '其他',
    temporal      INTEGER DEFAULT 0,
    expires_at    TEXT,
    source_msg_id INTEGER,
    created_at    TEXT NOT NULL,
    last_seen     TEXT,
    active        INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_fact_scope ON facts(scope, active);

CREATE TABLE IF NOT EXISTS distill_state (
    scope       TEXT PRIMARY KEY,
    last_msg_id INTEGER DEFAULT 0,
    updated_at  TEXT
);
"""

_conn: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
    return _conn


# ---------- 对话 ----------

def add_message(session_key: str, user_id: str | None, role: str, content: str) -> int:
    c = conn()
    cur = c.execute(
        "INSERT INTO messages (session_key, user_id, role, content, created_at) VALUES (?,?,?,?,?)",
        (session_key, user_id, role, content, _now()),
    )
    c.commit()
    return cur.lastrowid


def set_embedding(msg_id: int, blob: bytes) -> None:
    c = conn()
    c.execute("UPDATE messages SET embedding=? WHERE id=?", (blob, msg_id))
    c.commit()


def recent_messages(session_key: str, limit: int) -> list[dict]:
    c = conn()
    rows = c.execute(
        "SELECT id, user_id, role, content FROM messages WHERE session_key=? ORDER BY id DESC LIMIT ?",
        (session_key, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def messages_with_embedding(session_key: str) -> list[dict]:
    c = conn()
    rows = c.execute(
        "SELECT id, user_id, role, content, embedding FROM messages "
        "WHERE session_key=? AND embedding IS NOT NULL AND role='user' ORDER BY id DESC",
        (session_key,),
    ).fetchall()
    return [dict(r) for r in rows]


def messages_after(session_key: str, after_id: int) -> list[dict]:
    c = conn()
    rows = c.execute(
        "SELECT id, user_id, role, content FROM messages WHERE session_key=? AND id>? ORDER BY id",
        (session_key, after_id),
    ).fetchall()
    return [dict(r) for r in rows]


def max_message_id(session_key: str) -> int:
    c = conn()
    row = c.execute("SELECT MAX(id) AS m FROM messages WHERE session_key=?", (session_key,)).fetchone()
    return row["m"] or 0


# ---------- 事实 ----------

def add_fact(
    scope: str,
    content: str,
    category: str = "其他",
    temporal: bool = False,
    days: int | None = None,
    source_msg_id: int | None = None,
) -> int | None:
    """写入一条事实。已存在相同内容（未失效）则跳过，返回 None。"""
    c = conn()
    exists = c.execute(
        "SELECT id FROM facts WHERE scope=? AND content=? AND active=1", (scope, content)
    ).fetchone()
    if exists:
        c.execute("UPDATE facts SET last_seen=? WHERE id=?", (_now(), exists["id"]))
        c.commit()
        return None

    expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days else None
    cur = c.execute(
        "INSERT INTO facts (scope, content, category, temporal, expires_at, source_msg_id, created_at, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (scope, content, category, 1 if temporal else 0, expires, source_msg_id, _now(), _now()),
    )
    c.commit()
    return cur.lastrowid


def list_facts(scope: str, include_expired: bool = False) -> list[dict]:
    c = conn()
    sql = "SELECT id, content, category, temporal, expires_at, created_at FROM facts WHERE scope=? AND active=1"
    if not include_expired:
        sql += " AND (expires_at IS NULL OR expires_at > datetime('now','localtime'))"
    sql += " ORDER BY temporal, id"
    return [dict(r) for r in c.execute(sql, (scope,)).fetchall()]


def deactivate_fact(scope: str, keyword: str) -> int:
    c = conn()
    cur = c.execute(
        "UPDATE facts SET active=0 WHERE scope=? AND active=1 AND content LIKE ?",
        (scope, f"%{keyword}%"),
    )
    c.commit()
    return cur.rowcount


def clear_facts(scope: str) -> int:
    c = conn()
    cur = c.execute("UPDATE facts SET active=0 WHERE scope=? AND active=1", (scope,))
    c.commit()
    return cur.rowcount


def prune_facts(scope: str, keep: int = 80) -> int:
    """事实太多时，按最后提及时间淘汰最旧的。"""
    c = conn()
    rows = c.execute(
        "SELECT id FROM facts WHERE scope=? AND active=1 ORDER BY COALESCE(last_seen, created_at) DESC",
        (scope,),
    ).fetchall()
    if len(rows) <= keep:
        return 0
    stale = [r["id"] for r in rows[keep:]]
    c.executemany("UPDATE facts SET active=0 WHERE id=?", [(i,) for i in stale])
    c.commit()
    return len(stale)


def all_scopes() -> list[str]:
    c = conn()
    rows = c.execute("SELECT DISTINCT session_key AS s FROM messages").fetchall()
    return [r["s"] for r in rows]


# ---------- 提炼进度 ----------

def get_distill_cursor(scope: str) -> int:
    c = conn()
    row = c.execute("SELECT last_msg_id FROM distill_state WHERE scope=?", (scope,)).fetchone()
    return row["last_msg_id"] if row else 0


def set_distill_cursor(scope: str, msg_id: int) -> None:
    c = conn()
    c.execute(
        "INSERT INTO distill_state (scope, last_msg_id, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(scope) DO UPDATE SET last_msg_id=excluded.last_msg_id, updated_at=excluded.updated_at",
        (scope, msg_id, _now()),
    )
    c.commit()
