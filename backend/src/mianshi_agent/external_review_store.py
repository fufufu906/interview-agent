"""Private, revision-checked external reviews and durable per-item jobs."""

import json
from uuid import uuid4

from mianshi_agent.db import Database, utcnow_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS external_reviews (
 review_id TEXT PRIMARY KEY,
 profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
 title TEXT NOT NULL, raw_text TEXT NOT NULL, raw_bytes BLOB NOT NULL,
 payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
 revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_external_reviews_profile ON external_reviews(profile_id,created_at);
CREATE TABLE IF NOT EXISTS external_review_jobs (
 job_id TEXT PRIMARY KEY,
 review_id TEXT NOT NULL REFERENCES external_reviews(review_id) ON DELETE CASCADE,
 profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
 kind TEXT NOT NULL, item_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', result_json TEXT, error TEXT,
 UNIQUE(review_id,kind,item_id)
);
"""


class ExternalReviewStore:
    def __init__(self, db: Database):
        self.db = db

    async def initialize(self):
        async with self.db.connect() as c:
            await c.executescript(SCHEMA)
            await c.execute(
                "UPDATE external_review_jobs SET status='queued' WHERE status='generating'"
            )
            await c.commit()

    async def create(self, pid, title, raw, turns, raw_bytes):
        await self.db.require_profile(pid)
        rid, now = f"external_{uuid4().hex}", utcnow_iso()
        payload = {"turns": turns, "role": {"title": "", "jd_text": ""}, "warnings": []}
        async with self.db.connect() as c:
            await c.execute(
                "INSERT INTO external_reviews VALUES(?,?,?,?,?,?,'draft',0,?,?)",
                (
                    rid,
                    pid,
                    title,
                    raw,
                    raw_bytes,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            await c.commit()
        return rid

    async def get(self, pid, rid):
        async with self.db.connect() as c:
            cur = await c.execute(
                "SELECT * FROM external_reviews WHERE profile_id=? AND review_id=?", (pid, rid)
            )
            row = await cur.fetchone()
            if row is None:
                raise KeyError("external_review_not_found")
            result = dict(row)
            result.update(json.loads(result.pop("payload_json")))
            cur = await c.execute(
                "SELECT * FROM external_review_jobs WHERE profile_id=? AND review_id=? "
                "ORDER BY ordinal",
                (pid, rid),
            )
            result["jobs"] = [
                {**dict(j), "result": json.loads(j["result_json"]) if j["result_json"] else None}
                for j in await cur.fetchall()
            ]
        return result

    async def list(self, pid):
        async with self.db.connect() as c:
            cur = await c.execute(
                "SELECT review_id,title,status,revision,created_at,updated_at "
                "FROM external_reviews "
                "WHERE profile_id=? ORDER BY created_at DESC",
                (pid,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def update(self, pid, rid, revision, payload, status="draft", jobs=None):
        async with self.db.connect() as c:
            await c.execute("BEGIN IMMEDIATE")
            cur = await c.execute(
                "UPDATE external_reviews SET payload_json=?,status=?,"
                "revision=revision+1,updated_at=? "
                "WHERE profile_id=? AND review_id=? AND revision=? AND status IN ('draft','error')",
                (json.dumps(payload, ensure_ascii=False), status, utcnow_iso(), pid, rid, revision),
            )
            if cur.rowcount != 1:
                raise RuntimeError("external_review_revision_conflict")
            if jobs is not None:
                await c.execute(
                    "DELETE FROM external_review_jobs WHERE profile_id=? AND review_id=?",
                    (pid, rid),
                )
                await c.executemany(
                    "INSERT INTO external_review_jobs"
                    "(job_id,review_id,profile_id,kind,item_id,ordinal) "
                    "VALUES(?,?,?,?,?,?)",
                    [(uuid4().hex, rid, pid, kind, item, i) for i, (kind, item) in enumerate(jobs)],
                )
            await c.commit()

    async def claim(self):
        async with self.db.connect() as c:
            await c.execute("BEGIN IMMEDIATE")
            cur = await c.execute(
                "SELECT j.* FROM external_review_jobs j JOIN external_reviews r "
                "ON r.review_id=j.review_id AND r.profile_id=j.profile_id "
                "WHERE j.status='queued' AND r.status IN ('parsing','generating','error') "
                "AND (j.kind!='summary' OR NOT EXISTS(SELECT 1 FROM external_review_jobs a "
                "WHERE a.review_id=j.review_id AND a.kind='analyze' AND a.status!='ready')) "
                "ORDER BY r.created_at,j.ordinal LIMIT 1"
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await c.execute(
                "UPDATE external_review_jobs SET status='generating' WHERE job_id=?",
                (row["job_id"],),
            )
            await c.commit()
            return dict(row)

    async def finish_job(self, job, result=None, error=None, payload=None):
        async with self.db.connect() as c:
            await c.execute("BEGIN IMMEDIATE")
            await c.execute(
                "UPDATE external_review_jobs SET status=?,result_json=?,error=? WHERE job_id=? "
                "AND profile_id=? AND status='generating'",
                (
                    "error" if error else "ready",
                    json.dumps(result, ensure_ascii=False),
                    error,
                    job["job_id"],
                    job["profile_id"],
                ),
            )
            if payload is not None:
                await c.execute(
                    "UPDATE external_reviews SET payload_json=?,revision=revision+1 "
                    "WHERE review_id=? "
                    "AND profile_id=?",
                    (json.dumps(payload, ensure_ascii=False), job["review_id"], job["profile_id"]),
                )
            cur = await c.execute(
                "SELECT kind,status FROM external_review_jobs WHERE review_id=? AND profile_id=?",
                (job["review_id"], job["profile_id"]),
            )
            rows = await cur.fetchall()
            pending = any(
                r["status"] in ("queued", "generating") and r["kind"] != "summary" for r in rows
            )
            parsing = all(r["kind"] == "parse" for r in rows)
            if parsing:
                status = "parsing" if pending else "draft"
            elif any(r["status"] == "error" for r in rows) and not pending:
                status = "error"
            else:
                status = "completed" if all(r["status"] == "ready" for r in rows) else "generating"
            await c.execute(
                "UPDATE external_reviews SET status=?,updated_at=? "
                "WHERE profile_id=? AND review_id=?",
                (status, utcnow_iso(), job["profile_id"], job["review_id"]),
            )
            await c.commit()

    async def retry(self, pid, rid):
        await self.get(pid, rid)
        async with self.db.connect() as c:
            await c.execute(
                "UPDATE external_review_jobs SET status='queued',error=NULL WHERE profile_id=? "
                "AND review_id=? AND status='error' AND kind IN ('analyze','summary')",
                (pid, rid),
            )
            await c.execute(
                "UPDATE external_reviews SET status='generating',updated_at=? WHERE profile_id=? "
                "AND review_id=? AND status='error'",
                (utcnow_iso(), pid, rid),
            )
            await c.commit()
