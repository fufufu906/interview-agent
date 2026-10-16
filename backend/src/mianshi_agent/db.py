"""SQLite persistence with strict profile-scoped queries."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import aiosqlite


def utcnow_iso() -> str:
    """Return a stable UTC timestamp for persistence."""
    return datetime.now(UTC).isoformat()


def source_folder_root(metadata: dict[str, Any]) -> str | None:
    """Adapt legacy repository provenance without rewriting stored sources."""
    explicit = metadata.get("folder_root")
    if isinstance(explicit, str) and explicit:
        return explicit
    local = metadata.get("local_path")
    relative = metadata.get("relative_path")
    if not isinstance(local, str) or not isinstance(relative, str) or not relative:
        return None
    normalized = relative.replace("\\", "/")
    parts = normalized.split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or PureWindowsPath(normalized).drive
        or PurePosixPath(normalized).is_absolute()
    ):
        return None
    windows = bool(PureWindowsPath(local).drive or "\\" in local)
    path = PureWindowsPath(local) if windows else PurePosixPath(local)
    if not path.is_absolute() or len(path.parts) <= len(parts):
        return None
    suffix = path.parts[-len(parts) :]
    if windows:
        matches = [part.casefold() for part in suffix] == [part.casefold() for part in parts]
    else:
        matches = list(suffix) == parts
    return str(path.parents[len(parts) - 1]) if matches else None


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_targets (
    role_target_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    jd_text TEXT NOT NULL,
    competencies_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_role_targets_profile ON role_targets(profile_id, active);

CREATE TABLE IF NOT EXISTS source_documents (
    source_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    origin_uri TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(profile_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_sources_profile ON source_documents(profile_id, active);

CREATE TABLE IF NOT EXISTS source_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_documents(source_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}',
    embedding_model TEXT,
    embedding_dimensions INTEGER,
    embedding_json TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunks_profile ON source_chunks(profile_id, active);

CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_chunk_id TEXT REFERENCES source_chunks(chunk_id) ON DELETE SET NULL,
    verification_status TEXT NOT NULL DEFAULT 'user_supplied',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_profile ON graph_nodes(profile_id, node_type);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    source_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
    target_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    source_chunk_id TEXT REFERENCES source_chunks(chunk_id) ON DELETE SET NULL,
    verification_status TEXT NOT NULL DEFAULT 'user_supplied',
    created_at TEXT NOT NULL,
    UNIQUE(profile_id, source_node_id, target_node_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_profile
ON graph_edges(profile_id, source_node_id, target_node_id);

CREATE TABLE IF NOT EXISTS interview_sessions (
    session_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    role_target_id TEXT NOT NULL REFERENCES role_targets(role_target_id) ON DELETE RESTRICT,
    mode TEXT NOT NULL,
    focus TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    max_prompts INTEGER NOT NULL,
    prompt_count INTEGER NOT NULL DEFAULT 0,
    review_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_profile
ON interview_sessions(profile_id, created_at);

CREATE TABLE IF NOT EXISTS interview_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES interview_sessions(session_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    speaker TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    competency TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    request_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, ordinal),
    UNIQUE(session_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_turns_session
ON interview_turns(profile_id, session_id, ordinal);

CREATE TABLE IF NOT EXISTS deep_studies (
    study_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_write_log (
    memory_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    session_id TEXT REFERENCES interview_sessions(session_id) ON DELETE CASCADE,
    source_id TEXT REFERENCES source_documents(source_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    classification_json TEXT NOT NULL,
    write_target TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(profile_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_write_scope
ON memory_write_log(profile_id, session_id, write_target);

CREATE TABLE IF NOT EXISTS interview_memory_answers (
    question_turn_id TEXT PRIMARY KEY REFERENCES interview_turns(turn_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES interview_sessions(session_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    payload_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_answer_queue
ON interview_memory_answers(status, created_at);
"""


class Database:
    """Own connections and keep all business reads profile-scoped."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        """Create the runtime directory and idempotent schema."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await connection.executescript(SCHEMA)
            columns = await connection.execute("PRAGMA table_info(interview_sessions)")
            if "generation_stage" not in {row[1] for row in await columns.fetchall()}:
                await connection.execute(
                    "ALTER TABLE interview_sessions ADD COLUMN generation_stage "
                    "TEXT NOT NULL DEFAULT 'question'"
                )
            await connection.commit()

    async def record_memory_write(
        self,
        profile_id: str,
        memory_id: str,
        event_id: str,
        request: dict[str, Any],
        decision: dict[str, Any],
    ) -> None:
        async with self.connect() as connection:
            profile = await self._fetchone(
                connection,
                "SELECT profile_id FROM profiles WHERE profile_id = ?",
                (profile_id,),
            )
            if profile is None:
                raise KeyError("profile_not_found")
            if request["session_id"]:
                session = await self._fetchone(
                    connection,
                    "SELECT session_id FROM interview_sessions WHERE profile_id = ? "
                    "AND session_id = ?",
                    (profile_id, request["session_id"]),
                )
                if session is None:
                    raise KeyError("interview_session_not_found")
            if request["source_id"]:
                source = await self._fetchone(
                    connection,
                    "SELECT source_id FROM source_documents WHERE profile_id = ? AND source_id = ?",
                    (profile_id, request["source_id"]),
                )
                if source is None:
                    raise KeyError("source_not_found")
            await connection.execute(
                "INSERT INTO memory_write_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(profile_id, event_id) DO NOTHING",
                (
                    memory_id,
                    profile_id,
                    event_id,
                    request["session_id"],
                    request["source_id"],
                    request["content"],
                    json.dumps(decision, ensure_ascii=False),
                    decision["write_target"],
                    utcnow_iso(),
                ),
            )
            await connection.commit()

    async def memory_event_ids(self, profile_id: str, session_id: str) -> set[str]:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT event_id FROM memory_write_log WHERE profile_id = ? AND session_id = ?",
                (profile_id, session_id),
            )
            return {row["event_id"] for row in await cursor.fetchall()}

    async def list_short_term_memory(
        self,
        profile_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        await self.get_interview_session(profile_id, session_id)
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT event_id, content FROM memory_write_log "
                "WHERE profile_id = ? AND session_id = ? AND write_target = 'short_term_memory' "
                "ORDER BY created_at, rowid",
                (profile_id, session_id),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def enqueue_memory_answers(self, profile_id: str, session_id: str) -> None:
        session = await self.get_interview_session(profile_id, session_id)
        if session["status"] != "completed":
            raise RuntimeError("memory_answers_require_completed_session")
        now = utcnow_iso()
        async with self.connect() as connection:
            await connection.executemany(
                "INSERT INTO interview_memory_answers "
                "(question_turn_id, profile_id, session_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'queued', ?, ?) "
                "ON CONFLICT(question_turn_id) DO UPDATE SET status = 'queued', "
                "error = NULL, updated_at = excluded.updated_at "
                "WHERE interview_memory_answers.status = 'error' "
                "AND interview_memory_answers.profile_id = excluded.profile_id "
                "AND interview_memory_answers.session_id = excluded.session_id",
                [
                    (t["turn_id"], profile_id, session_id, now, now)
                    for t in session["turns"]
                    if t["speaker"] == "interviewer"
                ],
            )
            await connection.commit()

    async def list_memory_answers(
        self,
        profile_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT a.* FROM interview_memory_answers a JOIN interview_turns t "
                "ON t.turn_id = a.question_turn_id AND t.profile_id = a.profile_id "
                "WHERE a.profile_id = ? AND a.session_id = ? ORDER BY t.ordinal",
                (profile_id, session_id),
            )
            rows = await cursor.fetchall()
        return [
            {
                "question_turn_id": row["question_turn_id"],
                "status": row["status"],
                "error": row["error"],
                "updated_at": row["updated_at"],
                **(json.loads(row["payload_json"]) if row["payload_json"] else {}),
            }
            for row in rows
        ]

    async def claim_memory_answer(self) -> dict[str, Any] | None:
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            row = await self._fetchone(
                connection,
                "SELECT a.* FROM interview_memory_answers a JOIN interview_sessions s "
                "ON s.session_id = a.session_id AND s.profile_id = a.profile_id "
                "WHERE a.status = 'queued' AND s.status = 'completed' "
                "ORDER BY a.created_at, a.rowid LIMIT 1",
                (),
            )
            if row is None:
                return None
            await connection.execute(
                "UPDATE interview_memory_answers SET status = 'generating', updated_at = ? "
                "WHERE question_turn_id = ? AND status = 'queued'",
                (utcnow_iso(), row["question_turn_id"]),
            )
            await connection.commit()
            return dict(row)

    async def save_memory_answer(
        self,
        profile_id: str,
        session_id: str,
        question_turn_id: str,
        payload: dict[str, Any] | None,
        *,
        error: str | None = None,
    ) -> None:
        async with self.connect() as connection:
            await connection.execute(
                "UPDATE interview_memory_answers SET status = ?, payload_json = ?, "
                "error = ?, updated_at = ? WHERE profile_id = ? AND session_id = ? "
                "AND question_turn_id = ? AND status = 'generating'",
                (
                    "error" if error else "ready",
                    json.dumps(payload, ensure_ascii=False) if payload else None,
                    error,
                    utcnow_iso(),
                    profile_id,
                    session_id,
                    question_turn_id,
                ),
            )
            await connection.commit()

    async def recover_memory_answers(self) -> None:
        async with self.connect() as connection:
            await connection.execute(
                "UPDATE interview_memory_answers SET status = 'queued', updated_at = ? "
                "WHERE status = 'generating'",
                (utcnow_iso(),),
            )
            await connection.commit()

    async def recover_interrupted_sessions(self) -> None:
        """Single-worker local startup makes interrupted requests retryable."""
        async with self.connect() as connection:
            await connection.execute(
                "UPDATE interview_sessions SET status = 'error', "
                "error = 'generation_interrupted', updated_at = ? WHERE status = 'generating'",
                (utcnow_iso(),),
            )
            await connection.commit()

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """Open one configured connection with dictionaries as rows."""
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            yield connection

    async def create_profile(self, profile_id: str, display_name: str) -> dict[str, Any]:
        """Create or update a profile without crossing its identifier boundary."""
        created_at = utcnow_iso()
        async with self.connect() as connection:
            await connection.execute(
                """
                INSERT INTO profiles(profile_id, display_name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET display_name = excluded.display_name
                """,
                (profile_id, display_name, created_at),
            )
            await connection.commit()
            row = await self._fetchone(
                connection,
                "SELECT * FROM profiles WHERE profile_id = ?",
                (profile_id,),
            )
        return dict(row)

    async def require_profile(self, profile_id: str) -> dict[str, Any]:
        """Return one profile or raise a stable lookup error."""
        async with self.connect() as connection:
            row = await self._fetchone(
                connection,
                "SELECT * FROM profiles WHERE profile_id = ?",
                (profile_id,),
            )
        if row is None:
            raise KeyError("profile_not_found")
        return dict(row)

    async def list_profiles(self) -> list[dict[str, Any]]:
        async with self.connect() as connection:
            cursor = await connection.execute("SELECT * FROM profiles ORDER BY created_at")
            return [dict(row) for row in await cursor.fetchall()]

    async def list_roles(self, profile_id: str) -> list[dict[str, Any]]:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM role_targets WHERE profile_id = ? ORDER BY created_at DESC",
                (profile_id,),
            )
            return [self._decode_role(row) for row in await cursor.fetchall()]

    async def activate_role(self, profile_id: str, role_target_id: str) -> dict[str, Any]:
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            row = await self._fetchone(
                connection,
                "SELECT * FROM role_targets WHERE profile_id = ? AND role_target_id = ?",
                (profile_id, role_target_id),
            )
            if row is None:
                raise KeyError("role_target_not_found")
            await connection.execute(
                "UPDATE role_targets SET active = (role_target_id = ?) WHERE profile_id = ?",
                (role_target_id, profile_id),
            )
            await connection.commit()
        return {**self._decode_role(row), "active": True}

    async def source_detail(self, profile_id: str, source_id: str) -> dict[str, Any]:
        async with self.connect() as connection:
            row = await self._fetchone(
                connection,
                "SELECT * FROM source_documents WHERE profile_id = ? AND source_id = ? "
                "AND active = 1",
                (profile_id, source_id),
            )
            if row is None:
                raise KeyError("source_not_found")
            cursor = await connection.execute(
                "SELECT chunk_id, text, locator_json FROM source_chunks "
                "WHERE profile_id = ? AND source_id = ? AND active = 1 ORDER BY ordinal",
                (profile_id, source_id),
            )
            chunks = [
                {
                    "chunk_id": c["chunk_id"],
                    "text": c["text"],
                    "locator": json.loads(c["locator_json"]),
                }
                for c in await cursor.fetchall()
            ]
        return {
            "source_id": source_id,
            "title": row["title"],
            "kind": row["kind"],
            "origin_uri": row["origin_uri"],
            "content_hash": row["content_hash"],
            "metadata": json.loads(row["metadata_json"]),
            "chunks": chunks,
        }

    async def list_interviews(self, profile_id: str) -> list[dict[str, Any]]:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT s.session_id, r.title AS role_title, s.focus, s.status, "
                "s.prompt_count, s.max_prompts, s.created_at, s.updated_at "
                "FROM interview_sessions s JOIN role_targets r "
                "ON s.role_target_id = r.role_target_id AND s.profile_id = r.profile_id "
                "WHERE s.profile_id = ? ORDER BY s.created_at DESC LIMIT 100",
                (profile_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def claim_interview_generation(
        self, profile_id: str, session_id: str, *, retry: bool = False
    ) -> None:
        async with self.connect() as connection:
            expected = "error" if retry else "awaiting_answer"
            cursor = await connection.execute(
                "UPDATE interview_sessions SET status = 'generating', error = NULL, "
                "generation_stage = CASE WHEN ? THEN generation_stage ELSE 'review' END, "
                "updated_at = ? WHERE profile_id = ? AND session_id = ? AND status = ?",
                (retry, utcnow_iso(), profile_id, session_id, expected),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("session_busy_or_not_retryable")
            await connection.commit()

    async def save_study(self, record: dict[str, Any]) -> None:
        async with self.connect() as connection:
            await connection.execute(
                "INSERT INTO deep_studies VALUES (?, ?, ?, ?)",
                (
                    record["study_id"],
                    record["profile_id"],
                    json.dumps(record, ensure_ascii=False),
                    record["created_at"],
                ),
            )
            await connection.commit()

    async def set_interview_review_stage(self, profile_id: str, session_id: str) -> None:
        """Persist the review boundary so retries never re-ask a completed question."""
        async with self.connect() as connection:
            cursor = await connection.execute(
                "UPDATE interview_sessions SET generation_stage = 'review' "
                "WHERE profile_id = ? AND session_id = ? AND status = 'generating'",
                (profile_id, session_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("session_not_generating")
            await connection.commit()

    async def list_studies(self, profile_id: str) -> list[dict[str, Any]]:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT payload_json FROM deep_studies WHERE profile_id = ? "
                "ORDER BY created_at DESC LIMIT 50",
                (profile_id,),
            )
            return [json.loads(row["payload_json"]) for row in await cursor.fetchall()]

    async def create_role_target(self, record: dict[str, Any]) -> dict[str, Any]:
        """Store a target role and atomically select it when requested."""
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            if record["active"]:
                await connection.execute(
                    "UPDATE role_targets SET active = 0 WHERE profile_id = ?",
                    (record["profile_id"],),
                )
            await connection.execute(
                """
                INSERT INTO role_targets(
                    role_target_id, profile_id, title, level, company, jd_text,
                    competencies_json, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["role_target_id"],
                    record["profile_id"],
                    record["title"],
                    record["level"],
                    record["company"],
                    record["jd_text"],
                    json.dumps(record["competencies"], ensure_ascii=False),
                    int(record["active"]),
                    record["created_at"],
                ),
            )
            await connection.commit()
            row = await self._fetchone(
                connection,
                "SELECT * FROM role_targets WHERE profile_id = ? AND role_target_id = ?",
                (record["profile_id"], record["role_target_id"]),
            )
        return self._decode_role(row)

    async def get_active_role_target(self, profile_id: str) -> dict[str, Any]:
        """Return the currently selected target role for a profile."""
        async with self.connect() as connection:
            row = await self._fetchone(
                connection,
                """
                SELECT * FROM role_targets
                WHERE profile_id = ? AND active = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                (profile_id,),
            )
        if row is None:
            raise KeyError("active_role_not_found")
        return self._decode_role(row)

    async def get_role_target(self, profile_id: str, role_target_id: str) -> dict[str, Any]:
        """Load the role snapshot bound to an existing session."""
        async with self.connect() as connection:
            row = await self._fetchone(
                connection,
                """
                SELECT * FROM role_targets
                WHERE profile_id = ? AND role_target_id = ?
                """,
                (profile_id, role_target_id),
            )
        if row is None:
            raise KeyError("role_target_not_found")
        return self._decode_role(row)

    async def insert_source_with_chunks(
        self,
        source: dict[str, Any],
        chunks: Iterable[dict[str, Any]],
    ) -> None:
        """Commit a document and every derived chunk as one transaction."""
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                """
                INSERT INTO source_documents(
                    source_id, profile_id, kind, title, origin_uri, content_hash,
                    raw_text, metadata_json, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    source["source_id"],
                    source["profile_id"],
                    source["kind"],
                    source["title"],
                    source["origin_uri"],
                    source["content_hash"],
                    source["raw_text"],
                    json.dumps(source["metadata"], ensure_ascii=False),
                    source["created_at"],
                ),
            )
            await connection.executemany(
                """
                INSERT INTO source_chunks(
                    chunk_id, source_id, profile_id, ordinal, text, locator_json,
                    embedding_model, embedding_dimensions, embedding_json, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                [
                    (
                        item["chunk_id"],
                        source["source_id"],
                        source["profile_id"],
                        item["ordinal"],
                        item["text"],
                        json.dumps(item["locator"], ensure_ascii=False),
                        item.get("embedding_model"),
                        item.get("embedding_dimensions"),
                        json.dumps(item["embedding"]) if item.get("embedding") else None,
                        source["created_at"],
                    )
                    for item in chunks
                ],
            )
            await connection.commit()

    async def find_source_by_hash(
        self, profile_id: str, content_hash: str
    ) -> dict[str, Any] | None:
        """Deduplicate only within one profile."""
        async with self.connect() as connection:
            row = await self._fetchone(
                connection,
                """
                SELECT d.*, COUNT(c.chunk_id) AS chunk_count
                FROM source_documents d
                LEFT JOIN source_chunks c ON c.source_id = d.source_id AND c.active = 1
                WHERE d.profile_id = ? AND d.content_hash = ? AND d.active = 1
                GROUP BY d.source_id
                """,
                (profile_id, content_hash),
            )
        return dict(row) if row else None

    async def deactivate_other_source_versions(
        self,
        profile_id: str,
        origin_uri: str,
        current_source_id: str,
    ) -> int:
        """Deactivate older versions of the same imported repository file."""
        async with self.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE source_documents
                SET active = 0
                WHERE profile_id = ? AND origin_uri = ? AND source_id != ? AND active = 1
                """,
                (profile_id, origin_uri, current_source_id),
            )
            await connection.commit()
        return cursor.rowcount

    async def list_chunks(
        self,
        profile_id: str,
        *,
        for_memory: bool = False,
    ) -> list[dict[str, Any]]:
        """Return active chunks with source labels inside one profile."""
        async with self.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT c.*, d.title AS source_title, d.kind AS source_kind,
                       d.metadata_json AS source_metadata_json
                FROM source_chunks c
                JOIN source_documents d
                  ON d.source_id = c.source_id AND d.profile_id = c.profile_id
                WHERE c.profile_id = ? AND c.active = 1 AND d.active = 1
                ORDER BY d.created_at, c.ordinal
                """,
                (profile_id,),
            )
            rows = await cursor.fetchall()
        chunks = []
        for row in rows:
            item = dict(row)
            metadata = json.loads(item.pop("source_metadata_json"))
            if for_memory:
                from mianshi_agent.memory_write import MemoryWriteRequest, MemoryWriteRouter

                decision = MemoryWriteRouter.classify_rule(
                    MemoryWriteRequest(
                        content=item["text"],
                        source_kind=item["source_kind"],
                        source_title=item["source_title"],
                        metadata=metadata,
                    )
                )
                if decision is None or decision.write_target != "long_term_memory":
                    continue
            chunks.append(self._decode_chunk(item))
        return chunks

    async def list_sources(self, profile_id: str) -> list[dict[str, Any]]:
        """List source metadata and embedding coverage inside one profile."""
        async with self.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT d.source_id, d.profile_id, d.kind, d.title, d.content_hash,
                       d.created_at, d.metadata_json,
                       json_extract(d.metadata_json, '$.folder_root') AS folder_root,
                       json_extract(d.metadata_json, '$.relative_path') AS relative_path,
                       COUNT(c.chunk_id) AS chunk_count,
                       SUM(CASE WHEN c.embedding_json IS NOT NULL THEN 1 ELSE 0 END)
                           AS embedded_count
                FROM source_documents d
                LEFT JOIN source_chunks c
                  ON c.source_id = d.source_id AND c.active = 1
                WHERE d.profile_id = ? AND d.active = 1
                GROUP BY d.source_id
                ORDER BY d.created_at DESC
                """,
                (profile_id,),
            )
            rows = await cursor.fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["folder_root"] = source_folder_root(json.loads(item.pop("metadata_json")))
            items.append(item)
        return items

    async def list_chunks_without_embeddings(self, profile_id: str) -> list[dict[str, Any]]:
        """Find chunks that need semantic indexing inside one profile."""
        async with self.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT chunk_id, text
                FROM source_chunks
                WHERE profile_id = ? AND active = 1 AND embedding_json IS NULL
                ORDER BY created_at, ordinal
                """,
                (profile_id,),
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_chunk_embeddings(
        self,
        profile_id: str,
        records: Iterable[dict[str, Any]],
    ) -> None:
        """Persist generated vectors while enforcing the profile boundary."""
        rows = list(records)
        if not rows:
            return
        async with self.connect() as connection:
            await connection.executemany(
                """
                UPDATE source_chunks
                SET embedding_model = ?, embedding_dimensions = ?, embedding_json = ?
                WHERE profile_id = ? AND chunk_id = ? AND active = 1
                """,
                [
                    (
                        item["embedding_model"],
                        item["embedding_dimensions"],
                        json.dumps(item["embedding"]),
                        profile_id,
                        item["chunk_id"],
                    )
                    for item in rows
                ],
            )
            await connection.commit()

    async def create_graph_nodes_and_edges(
        self,
        nodes: Iterable[dict[str, Any]],
        edges: Iterable[dict[str, Any]],
    ) -> None:
        """Insert graph records idempotently after profile validation."""
        node_rows = list(nodes)
        edge_rows = list(edges)
        if not node_rows:
            return
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.executemany(
                """
                INSERT INTO graph_nodes(
                    node_id, profile_id, node_type, name, description, source_chunk_id,
                    verification_status, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    source_chunk_id = excluded.source_chunk_id,
                    verification_status = excluded.verification_status,
                    metadata_json = excluded.metadata_json,
                    created_at = excluded.created_at
                WHERE graph_nodes.profile_id = excluded.profile_id
                """,
                [
                    (
                        item["node_id"],
                        item["profile_id"],
                        item["node_type"],
                        item["name"],
                        item.get("description", ""),
                        item.get("source_chunk_id"),
                        item.get("verification_status", "user_supplied"),
                        json.dumps(item.get("metadata", {}), ensure_ascii=False),
                        item["created_at"],
                    )
                    for item in node_rows
                ],
            )
            if edge_rows:
                await connection.executemany(
                    """
                    INSERT OR IGNORE INTO graph_edges(
                        edge_id, profile_id, source_node_id, target_node_id, edge_type,
                        weight, source_chunk_id, verification_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item["edge_id"],
                            item["profile_id"],
                            item["source_node_id"],
                            item["target_node_id"],
                            item["edge_type"],
                            item.get("weight", 1.0),
                            item.get("source_chunk_id"),
                            item.get("verification_status", "user_supplied"),
                            item["created_at"],
                        )
                        for item in edge_rows
                    ],
                )
            await connection.commit()

    async def expand_chunks(
        self,
        profile_id: str,
        seed_chunk_ids: list[str],
        *,
        max_hops: int,
        max_nodes: int,
    ) -> tuple[dict[str, int], int]:
        """Walk a bounded undirected profile-scoped subgraph from evidence chunks."""
        if not seed_chunk_ids or max_hops <= 0:
            return {}, 0
        placeholders = ",".join("?" for _ in seed_chunk_ids)
        async with self.connect() as connection:
            cursor = await connection.execute(
                f"""
                SELECT node_id, source_chunk_id FROM graph_nodes
                WHERE profile_id = ? AND source_chunk_id IN ({placeholders})
                """,
                (profile_id, *seed_chunk_ids),
            )
            seeds = await cursor.fetchall()
            frontier = {row["node_id"] for row in seeds}
            visited = set(frontier)
            chunk_distances: dict[str, int] = {}
            for distance in range(1, max_hops + 1):
                if not frontier or len(visited) >= max_nodes:
                    break
                node_placeholders = ",".join("?" for _ in frontier)
                cursor = await connection.execute(
                    f"""
                    SELECT source_node_id, target_node_id
                    FROM graph_edges
                    WHERE profile_id = ? AND (
                        source_node_id IN ({node_placeholders})
                        OR target_node_id IN ({node_placeholders})
                    )
                    """,
                    (profile_id, *frontier, *frontier),
                )
                rows = await cursor.fetchall()
                neighbors = {
                    node_id
                    for row in rows
                    for node_id in (row["source_node_id"], row["target_node_id"])
                    if node_id not in visited
                }
                neighbors = set(list(neighbors)[: max(0, max_nodes - len(visited))])
                if not neighbors:
                    break
                neighbor_placeholders = ",".join("?" for _ in neighbors)
                cursor = await connection.execute(
                    f"""
                    SELECT source_chunk_id FROM graph_nodes
                    WHERE profile_id = ? AND node_id IN ({neighbor_placeholders})
                      AND source_chunk_id IS NOT NULL
                    """,
                    (profile_id, *neighbors),
                )
                for row in await cursor.fetchall():
                    chunk_distances.setdefault(row["source_chunk_id"], distance)
                visited.update(neighbors)
                frontier = neighbors
        return chunk_distances, len(visited)

    async def create_interview_session(self, record: dict[str, Any]) -> dict[str, Any]:
        """Create a session in generating state before the first model call."""
        async with self.connect() as connection:
            await connection.execute(
                """
                INSERT INTO interview_sessions(
                    session_id, profile_id, role_target_id, mode, focus, status,
                    max_prompts, prompt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'generating', ?, 0, ?, ?)
                """,
                (
                    record["session_id"],
                    record["profile_id"],
                    record["role_target_id"],
                    record["mode"],
                    record["focus"],
                    record["max_prompts"],
                    record["created_at"],
                    record["created_at"],
                ),
            )
            await connection.commit()
        return await self.get_interview_session(record["profile_id"], record["session_id"])

    async def get_interview_session(self, profile_id: str, session_id: str) -> dict[str, Any]:
        """Load one session and ordered turns within its profile."""
        async with self.connect() as connection:
            row = await self._fetchone(
                connection,
                """
                SELECT * FROM interview_sessions
                WHERE profile_id = ? AND session_id = ?
                """,
                (profile_id, session_id),
            )
            if row is None:
                raise KeyError("interview_session_not_found")
            cursor = await connection.execute(
                """
                SELECT * FROM interview_turns
                WHERE profile_id = ? AND session_id = ?
                ORDER BY ordinal
                """,
                (profile_id, session_id),
            )
            turns = await cursor.fetchall()
        payload = dict(row)
        payload["review"] = (
            json.loads(payload.pop("review_json")) if payload["review_json"] else None
        )
        payload["turns"] = [self._decode_turn(turn) for turn in turns]
        payload["memory_answers"] = await self.list_memory_answers(profile_id, session_id)
        return payload

    async def accept_interview_answer(
        self,
        profile_id: str,
        session_id: str,
        turn: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Atomically accept one answer and block duplicate session advancement."""
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            existing = await self._fetchone(
                connection,
                """
                SELECT * FROM interview_turns
                WHERE profile_id = ? AND session_id = ? AND request_id = ?
                """,
                (profile_id, session_id, turn["request_id"]),
            )
            if existing is not None:
                await connection.commit()
                return self._decode_turn(existing), True
            session = await self._fetchone(
                connection,
                """
                SELECT status FROM interview_sessions
                WHERE profile_id = ? AND session_id = ?
                """,
                (profile_id, session_id),
            )
            if session is None:
                raise KeyError("interview_session_not_found")
            if session["status"] != "awaiting_answer":
                raise RuntimeError("session_not_awaiting_answer")
            ordinal = await self._next_turn_ordinal(connection, profile_id, session_id)
            await connection.execute(
                """
                INSERT INTO interview_turns(
                    turn_id, session_id, profile_id, ordinal, speaker, kind,
                    content, competency, evidence_json, request_id, created_at
                ) VALUES (?, ?, ?, ?, 'candidate', ?, ?, '', '[]', ?, ?)
                """,
                (
                    turn["turn_id"],
                    session_id,
                    profile_id,
                    ordinal,
                    turn.get("kind", "answer"),
                    turn["content"],
                    turn["request_id"],
                    turn["created_at"],
                ),
            )
            await connection.execute(
                """
                UPDATE interview_sessions
                SET status = 'generating', error = NULL, updated_at = ?,
                    generation_stage = 'question'
                WHERE profile_id = ? AND session_id = ?
                """,
                (turn["created_at"], profile_id, session_id),
            )
            await connection.commit()
            stored = await self._fetchone(
                connection,
                "SELECT * FROM interview_turns WHERE turn_id = ?",
                (turn["turn_id"],),
            )
        if stored is None:
            raise RuntimeError("answer insert was not visible")
        return self._decode_turn(stored), False

    async def append_interviewer_turn(
        self,
        profile_id: str,
        session_id: str,
        turn: dict[str, Any],
    ) -> dict[str, Any]:
        """Append a generated prompt and return the session to awaiting-answer state."""
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            session = await self._fetchone(
                connection,
                """
                SELECT status FROM interview_sessions
                WHERE profile_id = ? AND session_id = ?
                """,
                (profile_id, session_id),
            )
            if session is None:
                raise KeyError("interview_session_not_found")
            if session["status"] != "generating":
                raise RuntimeError("session_not_generating")
            ordinal = await self._next_turn_ordinal(connection, profile_id, session_id)
            await connection.execute(
                """
                INSERT INTO interview_turns(
                    turn_id, session_id, profile_id, ordinal, speaker, kind,
                    content, competency, evidence_json, request_id, created_at
                ) VALUES (?, ?, ?, ?, 'interviewer', ?, ?, ?, ?, NULL, ?)
                """,
                (
                    turn["turn_id"],
                    session_id,
                    profile_id,
                    ordinal,
                    turn["kind"],
                    turn["content"],
                    turn.get("competency", ""),
                    json.dumps(turn.get("evidence", []), ensure_ascii=False),
                    turn["created_at"],
                ),
            )
            await connection.execute(
                """
                UPDATE interview_sessions
                SET status = 'awaiting_answer', prompt_count = prompt_count + ?,
                    error = NULL, updated_at = ?
                WHERE profile_id = ? AND session_id = ?
                """,
                (
                    0 if turn["kind"] == "clarification" else 1,
                    turn["created_at"],
                    profile_id,
                    session_id,
                ),
            )
            await connection.commit()
            stored = await self._fetchone(
                connection,
                "SELECT * FROM interview_turns WHERE turn_id = ?",
                (turn["turn_id"],),
            )
        if stored is None:
            raise RuntimeError("question insert was not visible")
        return self._decode_turn(stored)

    async def complete_interview_session(
        self,
        profile_id: str,
        session_id: str,
        review: dict[str, Any],
        *,
        queue_memory_answers: bool = False,
    ) -> None:
        """Persist the end-of-session review and mark the session complete."""
        updated_at = utcnow_iso()
        async with self.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE interview_sessions
                SET status = 'completed', review_json = ?, error = NULL, updated_at = ?
                WHERE profile_id = ? AND session_id = ?
                  AND status IN ('generating', 'awaiting_answer', 'error')
                """,
                (
                    json.dumps(review, ensure_ascii=False),
                    updated_at,
                    profile_id,
                    session_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("session_cannot_be_completed")
            if queue_memory_answers:
                await connection.execute(
                    "INSERT INTO interview_memory_answers "
                    "(question_turn_id, profile_id, session_id, status, created_at, updated_at) "
                    "SELECT turn_id, profile_id, session_id, 'queued', ?, ? "
                    "FROM interview_turns WHERE profile_id = ? AND session_id = ? "
                    "AND speaker = 'interviewer' ON CONFLICT(question_turn_id) DO NOTHING",
                    (updated_at, updated_at, profile_id, session_id),
                )
            await connection.commit()

    async def mark_interview_error(self, profile_id: str, session_id: str, error: str) -> None:
        """Keep a failed generation visible instead of pretending it completed."""
        async with self.connect() as connection:
            await connection.execute(
                """
                UPDATE interview_sessions
                SET status = 'error', error = ?, updated_at = ?
                WHERE profile_id = ? AND session_id = ? AND status = 'generating'
                """,
                (error[:500], utcnow_iso(), profile_id, session_id),
            )
            await connection.commit()

    @staticmethod
    async def _fetchone(
        connection: aiosqlite.Connection,
        query: str,
        parameters: tuple[Any, ...],
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(query, parameters)
        return await cursor.fetchone()

    @staticmethod
    def _decode_role(row: aiosqlite.Row | None) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("role insert was not visible")
        payload = dict(row)
        payload["competencies"] = json.loads(payload.pop("competencies_json"))
        payload["active"] = bool(payload["active"])
        return payload

    @staticmethod
    def _decode_chunk(row: aiosqlite.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["locator"] = json.loads(payload.pop("locator_json"))
        raw_embedding = payload.pop("embedding_json")
        payload["embedding"] = json.loads(raw_embedding) if raw_embedding else None
        payload["active"] = bool(payload["active"])
        return payload

    @staticmethod
    def _decode_turn(row: aiosqlite.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["evidence"] = json.loads(payload.pop("evidence_json"))
        payload.pop("request_id", None)
        payload.pop("session_id", None)
        payload.pop("profile_id", None)
        return payload

    @staticmethod
    async def _next_turn_ordinal(
        connection: aiosqlite.Connection,
        profile_id: str,
        session_id: str,
    ) -> int:
        row = await Database._fetchone(
            connection,
            """
            SELECT COALESCE(MAX(ordinal), -1) + 1 AS next_ordinal
            FROM interview_turns
            WHERE profile_id = ? AND session_id = ?
            """,
            (profile_id, session_id),
        )
        return int(row["next_ordinal"] if row else 0)
