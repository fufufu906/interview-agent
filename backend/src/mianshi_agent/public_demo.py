"""Public entrypoint: bounded anonymous workspaces, BYOK, no host-file APIs.

Each visitor gets an independent SQLite DB and service graph. The existing local
entrypoint is untouched; this module never reads backend/.env or private data.
Run one uvicorn worker. Public access must go through a same-origin HTTPS proxy.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mianshi_agent.config import Settings
from mianshi_agent.demo_credentials import DEEPSEEK_MODELS, VisitorChat
from mianshi_agent.demo_data import EXAMPLE, SOURCES
from mianshi_agent.embeddings import EmbeddingUnavailable
from mianshi_agent.main import create_app
from mianshi_agent.schemas import RoleTargetCreate, TextSourceCreate
from mianshi_agent.service import ProfileService

COOKIE = "__Host-interview_demo"
TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
FILE_ID = re.compile(r"^[a-f0-9]{64}$")
PROFILE = "visitor"


class DemoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEMO_", extra="ignore")
    data_dir: Path = Path("/app/data/public-demo")
    public_origin: str = "https://localhost"
    allow_http_local: bool = False
    session_seconds: int = Field(default=86400, ge=60, le=604800)
    key_seconds: int = Field(default=1800, ge=60, le=3600)
    max_visitors: int = Field(default=30, ge=1, le=200)
    max_active: int = Field(default=8, ge=1, le=30)
    max_request_bytes: int = Field(default=2_000_000, ge=1024, le=4_000_000)
    embedding_base_url: str = "http://ollama:11434"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dimensions: int = 1024

    @model_validator(mode="after")
    def check_origin(self):
        u = urlsplit(self.public_origin)
        local = self.allow_http_local and u.hostname in ("localhost", "127.0.0.1")
        if (
            (u.scheme != "https" and not (local and u.scheme == "http"))
            or not u.netloc
            or u.username
            or u.password
            or u.path not in ("", "/")
            or u.query
            or u.fragment
        ):
            raise ValueError("DEMO_PUBLIC_ORIGIN must be the exact public HTTPS origin")
        self.public_origin = self.public_origin.rstrip("/")
        self.data_dir = self.data_dir.resolve()
        return self


class DeferredEmbeddings:
    async def embed_documents(self, texts):
        raise EmbeddingUnavailable("demo_seed_not_indexed")


@dataclass
class Guest:
    app: FastAPI
    chat: VisitorChat
    lifespan: object
    metadata: dict
    last_used: float = field(default_factory=time.time)
    writing: bool = False
    requests: deque = field(default_factory=deque)


class Visitors:
    def __init__(self, settings: DemoSettings):
        self.settings = settings
        self.root = settings.data_dir
        self.guests: dict[str, Guest] = {}
        self.lock = asyncio.Lock()
        self.chat_slots = asyncio.Semaphore(2)
        self.creations: deque = deque()
        self.cookie_name = "interview_demo_local" if settings.allow_http_local else COOKIE

    def path(self, digest, suffix):
        if not FILE_ID.fullmatch(digest):
            raise HTTPException(401, "demo_session_required")
        return self.root / (digest + suffix)

    def save(self, digest, metadata):
        path = self.path(digest, ".json")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(metadata), encoding="utf-8")
        temp.replace(path)

    async def close(self, digest):
        guest = self.guests.pop(digest, None)
        if guest:
            guest.chat.disconnect()
            await guest.lifespan.__aexit__(None, None, None)

    async def clean(self):
        now = time.time()
        async with self.lock:
            for path in self.root.glob("*.json"):
                digest = path.stem
                if not FILE_ID.fullmatch(digest):
                    continue
                try:
                    meta = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                guest = self.guests.get(digest)
                if guest:
                    guest.chat.status()  # Actively erase expired credentials.
                if meta["expires_at"] < now:
                    if guest and (guest.writing or guest.chat.inflight):
                        continue
                    await self.close(digest)
                    # Only exact, validated filenames in the dedicated demo dir.
                    for suffix in (".sqlite3-wal", ".sqlite3-shm", ".sqlite3", ".json", ".tmp"):
                        self.path(digest, suffix).unlink(missing_ok=True)
                elif guest and now - guest.last_used > 300 and not guest.writing:
                    if not guest.chat.inflight:
                        await self.close(digest)

    async def create(self):
        await self.clean()
        async with self.lock:
            now = time.time()
            while self.creations and self.creations[0] < now - 60:
                self.creations.popleft()
            if len(self.creations) >= 5 or len(list(self.root.glob("*.json"))) >= (
                self.settings.max_visitors
            ):
                raise HTTPException(429, "demo_capacity_reached")
            self.creations.append(now)
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            self.save(digest, {"expires_at": now + self.settings.session_seconds, "binding": None})
        return token

    async def get(self, request: Request):
        token = request.cookies.get(self.cookie_name, "")
        if not TOKEN.fullmatch(token):
            raise HTTPException(401, "demo_session_required")
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self.lock:
            try:
                meta = json.loads(self.path(digest, ".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise HTTPException(401, "demo_session_required") from None
            if meta["expires_at"] <= time.time():
                raise HTTPException(401, "demo_session_expired")
            guest = self.guests.get(digest)
            if guest is None:
                if len(self.guests) >= self.settings.max_active:
                    raise HTTPException(429, "demo_capacity_reached")
                chat = VisitorChat(
                    token, meta["binding"], self.chat_slots, self.settings.key_seconds
                )
                settings = Settings(
                    _env_file=None,
                    app_data_dir=self.root,
                    app_database_path=self.path(digest, ".sqlite3"),
                    app_cors_origins=self.settings.public_origin,
                    app_max_upload_bytes=1_500_000,
                    llm_api_key="",
                    llm_base_url="",
                    memory_embedding_base_url=self.settings.embedding_base_url,
                    memory_embedding_model=self.settings.embedding_model,
                    memory_embedding_dimensions=self.settings.embedding_dimensions,
                    embedding_timeout=15,
                )
                child = create_app(settings, chat_client=chat)
                lifecycle = child.router.lifespan_context(child)
                await lifecycle.__aenter__()
                try:
                    db = child.state.database
                    if not await db.list_profiles():
                        await db.create_profile(PROFILE, "访客演示档案")
                        seed = ProfileService(db, settings, DeferredEmbeddings())
                        await seed.create_role_target(
                            PROFILE,
                            RoleTargetCreate(
                                title="AI 应用开发实习生 · 演示岗位",
                                jd_text="围绕资料检索、来源校验和异常处理，解释项目设计与实际职责。",
                                competencies=["资料检索", "证据与边界", "异常处理"],
                            ),
                        )
                        for source in SOURCES:
                            await seed.ingest_text(PROFILE, TextSourceCreate(**source))
                except BaseException:
                    await lifecycle.__aexit__(None, None, None)
                    raise
                guest = Guest(child, chat, lifecycle, meta)
                self.guests[digest] = guest
            guest.last_used = time.time()
            return digest, guest


def create_demo_app(settings: DemoSettings | None = None):
    settings = settings or DemoSettings()
    visitors = Visitors(settings)

    @asynccontextmanager
    async def lifespan(app):
        visitors.root.mkdir(parents=True, exist_ok=True)
        await visitors.clean()

        async def cleanup():
            while True:
                await asyncio.sleep(60)
                await visitors.clean()

        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            for digest in list(visitors.guests):
                await visitors.close(digest)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.visitors = visitors

    @app.middleware("http")
    async def public_headers(request: Request, call_next):
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if request.headers.get("x-interview-demo") != "1" or (
                origin and origin != settings.public_origin
            ):
                return Response(
                    '{"detail":"demo_origin_rejected"}', 403, media_type="application/json"
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "public_demo"}

    @app.get("/api/runtime")
    async def runtime():
        return {"mode": "public_demo", "models": DEEPSEEK_MODELS}

    @app.get("/api/demo/example")
    async def example():
        return EXAMPLE

    @app.post("/api/demo/visit")
    async def visit(request: Request, response: Response):
        # Reuse valid sessions; repeated clicks must not create empty databases.
        try:
            _, guest = await visitors.get(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            token = await visitors.create()
            response.set_cookie(
                visitors.cookie_name,
                token,
                httponly=True,
                samesite="strict",
                secure=not settings.allow_http_local,
                max_age=settings.session_seconds,
                path="/",
            )
            return {"created": True}
        return {"created": False, **guest.chat.status()}

    @app.get("/api/demo/credentials")
    async def credentials(request: Request):
        _, guest = await visitors.get(request)
        return guest.chat.status()

    async def body_of(request):
        parts, size = [], 0
        async for part in request.stream():
            size += len(part)
            if size > settings.max_request_bytes:
                raise HTTPException(413, "demo_request_too_large")
            parts.append(part)
        return b"".join(parts)

    @app.post("/api/demo/credentials")
    async def connect(request: Request):
        digest, guest = await visitors.get(request)
        try:
            body = json.loads(await body_of(request))
            if not isinstance(body, dict) or set(body) != {"api_key", "model"}:
                raise ValueError("demo_invalid_credentials")
            key, model = body["api_key"], body["model"]
            if not isinstance(key, str) or not isinstance(model, str):
                raise ValueError("demo_invalid_credentials")
            binding = guest.chat.connect(key, model)
        except (ValueError, TypeError):
            # Never return Pydantic errors containing the submitted secret input.
            raise HTTPException(422, "demo_credentials_rejected") from None
        guest.metadata["binding"] = binding
        visitors.save(digest, guest.metadata)
        return guest.chat.status()

    @app.delete("/api/demo/credentials")
    async def disconnect(request: Request):
        _, guest = await visitors.get(request)
        guest.chat.disconnect()
        return guest.chat.status()

    @app.post("/api/demo/reset")
    async def reset(request: Request, response: Response):
        digest, guest = await visitors.get(request)
        if guest.writing or guest.chat.inflight:
            raise HTTPException(409, "demo_busy")
        guest.chat.disconnect()
        guest.metadata["expires_at"] = 0
        visitors.save(digest, guest.metadata)
        response.delete_cookie(
            visitors.cookie_name,
            path="/",
            secure=not settings.allow_http_local,
            httponly=True,
            samesite="strict",
        )
        return {"reset": True}

    async def forward_unlocked(request: Request, path=""):
        digest, guest = await visitors.get(request)
        parts = path.split("/")
        if path and parts[0] != PROFILE:
            raise HTTPException(404, "profile_not_found")
        if "folder" in parts or "repository" in parts or "external-review-samples" in parts:
            if request.method == "GET" and parts[-1] == "external-review-samples":
                return []
            raise HTTPException(403, "demo_endpoint_disabled")
        if not path and request.method != "GET":
            raise HTTPException(403, "demo_endpoint_disabled")
        body = b""
        if request.method == "POST":
            now = time.time()
            while guest.requests and guest.requests[0] < now - 60:
                guest.requests.popleft()
            if len(guest.requests) >= 30:
                raise HTTPException(429, "demo_rate_limited")
            guest.requests.append(now)
            # Disallow generation and ingestion until a visitor Key is attached.
            # Never touch server-provided LLM_API_KEY, even if one exists.
            if not guest.chat.status()["connected"]:
                raise HTTPException(401, "demo_key_required")
            body = await body_of(request)
            dbfile = visitors.path(digest, ".sqlite3")
            if dbfile.stat().st_size > 30_000_000:
                raise HTTPException(413, "demo_workspace_full")
            counts = {
                f"{PROFILE}/sources/text": ("source_documents", 20),
                f"{PROFILE}/sources/file": ("source_documents", 20),
                f"{PROFILE}/roles": ("role_targets", 8),
                f"{PROFILE}/interviews": ("interview_sessions", 10),
                f"{PROFILE}/studies": ("deep_studies", 10),
                f"{PROFILE}/external-reviews": ("external_reviews", 8),
                f"{PROFILE}/external-reviews/upload": ("external_reviews", 8),
            }
            if path in counts:
                table, limit = counts[path]
                async with guest.app.state.database.connect() as conn:
                    row = await (await conn.execute(f"SELECT count(*) FROM {table}")).fetchone()
                if row[0] >= limit:
                    raise HTTPException(429, "demo_record_limit")
            if path == f"{PROFILE}/interviews":
                try:
                    payload = json.loads(body)
                    if int(payload.get("max_prompts", 8)) > 6:
                        raise ValueError
                except (ValueError, TypeError, AttributeError):
                    raise HTTPException(422, "demo_max_six_questions") from None
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=guest.app), base_url="http://workspace"
            ) as client:
                result = await client.request(
                    request.method,
                    request.url.path,
                    params=request.query_params,
                    headers={
                        k: v
                        for k, v in request.headers.items()
                        if k.lower() in ("content-type", "if-none-match")
                    },
                    content=body,
                )
            return Response(
                result.content,
                status_code=result.status_code,
                headers={
                    k: v
                    for k, v in result.headers.items()
                    if k.lower() in ("content-type", "etag", "content-disposition")
                },
            )
        finally:
            if request.method == "POST":
                guest.writing = False

    async def forward(request: Request, path=""):
        if request.method == "GET":
            return await forward_unlocked(request, path)
        _, guest = await visitors.get(request)
        if guest.writing:
            raise HTTPException(429, "demo_busy")
        guest.writing = True
        try:
            return await forward_unlocked(request, path)
        finally:
            guest.writing = False

    app.add_api_route("/api/profiles", forward, methods=["GET", "POST"])
    app.add_api_route("/api/profiles/{path:path}", forward, methods=["GET", "POST"])
    return app


app = create_demo_app()
