"""FastAPI entrypoint for the first MianshiAgent vertical slice."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from mianshi_agent.chat import ChatCompletionClient, ChatUnavailable
from mianshi_agent.config import Settings, get_settings
from mianshi_agent.db import Database
from mianshi_agent.documents import DocumentExtractionError, extract_document_text
from mianshi_agent.embeddings import OllamaEmbeddingClient
from mianshi_agent.external_review_api import external_review_router
from mianshi_agent.external_reviews import ExternalReviewService
from mianshi_agent.folder_import import FolderImportCreate, FolderImportService, FolderScanCreate
from mianshi_agent.interview import InterviewService
from mianshi_agent.memory_answers import MemoryAnswerService
from mianshi_agent.memory_write import MemoryWriteService
from mianshi_agent.retrieval import RetrievalService
from mianshi_agent.schemas import (
    DeepStudyCreate,
    DeepStudyResponse,
    InterviewAnswerCreate,
    InterviewSessionCreate,
    InterviewSessionResponse,
    InterviewStepResponse,
    InterviewSummary,
    ProfileCreate,
    ProfileResponse,
    ReindexResponse,
    RetrievalRequest,
    RetrievalResponse,
    RoleTargetCreate,
    RoleTargetResponse,
    SourceDetailResponse,
    SourceKind,
    SourceListResponse,
    SourceResponse,
    TextSourceCreate,
)
from mianshi_agent.service import ProfileService
from mianshi_agent.study import StudyService


def create_app(
    settings: Settings | None = None, *, chat_client: ChatCompletionClient | None = None
) -> FastAPI:
    """Build an app that can use isolated settings during tests."""
    resolved_settings = settings or get_settings()
    database = Database(resolved_settings.app_database_path)
    embeddings = OllamaEmbeddingClient(
        base_url=resolved_settings.memory_embedding_base_url,
        model=resolved_settings.memory_embedding_model,
        dimensions=resolved_settings.memory_embedding_dimensions,
        timeout=resolved_settings.embedding_timeout,
    )
    retrieval_service = RetrievalService(database, resolved_settings, embeddings)
    chat = chat_client or ChatCompletionClient(
        base_url=resolved_settings.llm_base_url,
        api_key=resolved_settings.llm_api_key,
        model=resolved_settings.llm_model_id,
        timeout=resolved_settings.llm_timeout,
    )
    memory_writer = MemoryWriteService(database, chat)
    profile_service = ProfileService(database, resolved_settings, embeddings, memory_writer)
    memory_answers = MemoryAnswerService(database, retrieval_service, chat, memory_writer)
    external_reviews = ExternalReviewService(database, retrieval_service, chat)
    interview_service = InterviewService(
        database,
        retrieval_service,
        chat,
        memory_answers,
        memory_writer,
    )
    study_service = StudyService(database, retrieval_service, chat)
    folder_service = FolderImportService(database, profile_service, chat)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await database.initialize()
        await database.recover_interrupted_sessions()
        await database.recover_memory_answers()
        await external_reviews.store.initialize()
        worker = asyncio.create_task(memory_answers.run())
        external_worker = asyncio.create_task(external_reviews.run())
        try:
            yield
        finally:
            worker.cancel()
            external_worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            with suppress(asyncio.CancelledError):
                await external_worker

    app = FastAPI(
        title="MianshiAgent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "If-None-Match", "X-Interview-Demo"],
    )

    async def profile_exists(profile_id: str) -> str:
        try:
            await database.require_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="profile_not_found") from exc
        return profile_id

    app.include_router(external_review_router(external_reviews, profile_exists))
    app.state.external_review_service = external_reviews

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/runtime")
    async def runtime() -> dict[str, str]:
        return {"mode": "local"}

    @app.post("/api/profiles", response_model=ProfileResponse)
    async def create_profile(request: ProfileCreate) -> ProfileResponse:
        record = await database.create_profile(request.profile_id, request.display_name)
        return ProfileResponse(**record)

    @app.get("/api/profiles", response_model=list[ProfileResponse])
    async def list_profiles():
        return await database.list_profiles()

    @app.get("/api/profiles/{profile_id}/roles", response_model=list[RoleTargetResponse])
    async def list_roles(profile_id: str = Depends(profile_exists)):
        return await database.list_roles(profile_id)

    @app.post(
        "/api/profiles/{profile_id}/roles/{role_target_id}/activate",
        response_model=RoleTargetResponse,
    )
    async def activate_role(role_target_id: str, profile_id: str = Depends(profile_exists)):
        try:
            return await database.activate_role(profile_id, role_target_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc

    @app.get("/api/profiles/{profile_id}/sources/{source_id}", response_model=SourceDetailResponse)
    async def source_detail(source_id: str, profile_id: str = Depends(profile_exists)):
        try:
            return await database.source_detail(profile_id, source_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc

    @app.get("/api/profiles/{profile_id}/interviews", response_model=list[InterviewSummary])
    async def list_interviews(profile_id: str = Depends(profile_exists)):
        return await database.list_interviews(profile_id)

    @app.post(
        "/api/profiles/{profile_id}/interviews/{session_id}/retry",
        response_model=InterviewSessionResponse,
    )
    async def retry_interview(session_id: str, profile_id: str = Depends(profile_exists)):
        try:
            return await interview_service.retry(profile_id, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except RuntimeError as exc:
            if isinstance(exc, ChatUnavailable):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=502, detail="invalid_model_response") from exc

    @app.get("/api/profiles/{profile_id}/studies", response_model=list[DeepStudyResponse])
    async def list_studies(profile_id: str = Depends(profile_exists)):
        return await database.list_studies(profile_id)

    @app.post("/api/profiles/{profile_id}/studies", response_model=DeepStudyResponse)
    async def create_study(request: DeepStudyCreate, profile_id: str = Depends(profile_exists)):
        try:
            return await study_service.create(profile_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ChatUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=502, detail="invalid_model_response") from exc

    @app.post(
        "/api/profiles/{profile_id}/roles",
        response_model=RoleTargetResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_role(
        request: RoleTargetCreate,
        profile_id: str = Depends(profile_exists),
    ) -> RoleTargetResponse:
        return await profile_service.create_role_target(profile_id, request)

    @app.post(
        "/api/profiles/{profile_id}/sources/text",
        response_model=SourceResponse,
    )
    async def import_text_source(
        request: TextSourceCreate,
        response: Response,
        profile_id: str = Depends(profile_exists),
        if_none_match: str | None = Header(default=None),
    ) -> SourceResponse:
        result = await profile_service.ingest_text(profile_id, request)
        response.status_code = (
            status.HTTP_200_OK if result.deduplicated else status.HTTP_201_CREATED
        )
        response.headers["ETag"] = f'"{result.response.content_hash}"'
        if if_none_match and if_none_match.strip('"') == result.response.content_hash:
            response.status_code = status.HTTP_304_NOT_MODIFIED
        return result.response

    @app.post(
        "/api/profiles/{profile_id}/sources/file",
        response_model=SourceResponse,
    )
    async def import_file_source(
        response: Response,
        file: Annotated[UploadFile, File()],
        kind: Annotated[SourceKind, Form()],
        title: Annotated[str | None, Form()] = None,
        profile_id: str = Depends(profile_exists),
    ) -> SourceResponse:
        content = await file.read(resolved_settings.app_max_upload_bytes + 1)
        if len(content) > resolved_settings.app_max_upload_bytes:
            raise HTTPException(status_code=413, detail="file_too_large")
        try:
            text = extract_document_text(file.filename or "upload", content)
        except DocumentExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = await profile_service.ingest_text(
            profile_id,
            TextSourceCreate(
                kind=kind,
                title=title or file.filename or "上传资料",
                text=text,
                origin_uri=file.filename or "",
                metadata={"filename": file.filename, "content_type": file.content_type},
            ),
        )
        response.status_code = (
            status.HTTP_200_OK if result.deduplicated else status.HTTP_201_CREATED
        )
        response.headers["ETag"] = f'"{result.response.content_hash}"'
        return result.response

    @app.post("/api/profiles/{profile_id}/sources/folder/scan")
    async def scan_folder(request: FolderScanCreate, profile_id: str = Depends(profile_exists)):
        try:
            return await folder_service.scan(profile_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/profiles/{profile_id}/sources/folder/import")
    async def import_folder(request: FolderImportCreate, profile_id: str = Depends(profile_exists)):
        try:
            return await folder_service.import_selected(profile_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/api/profiles/{profile_id}/sources",
        response_model=SourceListResponse,
    )
    async def list_sources(
        profile_id: str = Depends(profile_exists),
    ) -> SourceListResponse:
        rows = await database.list_sources(profile_id)
        return SourceListResponse(
            items=[
                SourceResponse(
                    source_id=row["source_id"],
                    profile_id=row["profile_id"],
                    kind=row["kind"],
                    title=row["title"],
                    content_hash=row["content_hash"],
                    chunk_count=row["chunk_count"],
                    embedding_status=(
                        "indexed"
                        if row["chunk_count"] and row["embedded_count"] == row["chunk_count"]
                        else "degraded"
                    ),
                    created_at=row["created_at"],
                    folder_root=row["folder_root"],
                    relative_path=row["relative_path"],
                )
                for row in rows
            ]
        )

    @app.post(
        "/api/profiles/{profile_id}/sources/reindex",
        response_model=ReindexResponse,
    )
    async def reindex_sources(
        profile_id: str = Depends(profile_exists),
    ) -> ReindexResponse:
        return await profile_service.reindex_missing_embeddings(profile_id)

    @app.post(
        "/api/profiles/{profile_id}/retrieve",
        response_model=RetrievalResponse,
    )
    async def retrieve(
        request: RetrievalRequest,
        profile_id: str = Depends(profile_exists),
    ) -> RetrievalResponse:
        return await retrieval_service.retrieve(
            profile_id,
            request.query,
            limit=request.limit,
            graph_hops=request.graph_hops,
        )

    @app.post(
        "/api/profiles/{profile_id}/interviews",
        response_model=InterviewStepResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def start_interview(
        request: InterviewSessionCreate,
        profile_id: str = Depends(profile_exists),
    ) -> InterviewStepResponse:
        if request.mode != "quick":
            raise HTTPException(status_code=422, detail="use_study_endpoint_for_deep_mode")
        try:
            return await interview_service.start(profile_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc.args[0])) from exc
        except (ChatUnavailable, ValidationError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get(
        "/api/profiles/{profile_id}/interviews/{session_id}",
        response_model=InterviewSessionResponse,
    )
    async def get_interview(
        session_id: str,
        profile_id: str = Depends(profile_exists),
    ) -> InterviewSessionResponse:
        try:
            return await interview_service.get(profile_id, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc

    @app.post(
        "/api/profiles/{profile_id}/interviews/{session_id}/answers",
        response_model=InterviewStepResponse,
    )
    async def answer_interview(
        session_id: str,
        request: InterviewAnswerCreate,
        profile_id: str = Depends(profile_exists),
    ) -> InterviewStepResponse:
        try:
            return await interview_service.answer(profile_id, session_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except (ChatUnavailable, ValidationError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/profiles/{profile_id}/interviews/{session_id}/finish",
        response_model=InterviewSessionResponse,
    )
    async def finish_interview(
        session_id: str,
        profile_id: str = Depends(profile_exists),
    ) -> InterviewSessionResponse:
        try:
            return await interview_service.finish(profile_id, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except (ChatUnavailable, ValidationError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/profiles/{profile_id}/interviews/{session_id}/memory-answers",
        response_model=InterviewSessionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def generate_memory_answers(
        session_id: str,
        profile_id: str = Depends(profile_exists),
    ) -> InterviewSessionResponse:
        try:
            await memory_answers.enqueue(profile_id, session_id)
            return await interview_service.get(profile_id, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    app.state.memory_answer_service = memory_answers
    app.state.memory_write_service = memory_writer
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.profile_service = profile_service
    app.state.retrieval_service = retrieval_service
    app.state.interview_service = interview_service
    app.state.study_service = study_service
    app.state.folder_service = folder_service
    return app


def __getattr__(name: str):
    # uvicorn main:app remains compatible; importing the factory for the public
    # gateway must not instantiate the personal app or read its dotenv file.
    if name == "app":
        application = create_app()
        globals()[name] = application
        return application
    raise AttributeError(name)
