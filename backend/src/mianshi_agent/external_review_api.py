"""External transcript import, confirmation, reports and document export API."""

from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi import File as Upload

from mianshi_agent.review_export import export_review
from mianshi_agent.transcripts import (
    TranscriptConfirm,
    TranscriptCreate,
    TranscriptRevision,
    TranscriptSplit,
)


def external_review_router(service, profile_exists):
    router = APIRouter(prefix="/api/profiles/{profile_id}")

    async def call(operation):
        try:
            return await operation
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/external-reviews")
    async def listing(profile_id: str = Depends(profile_exists)):
        return await service.store.list(profile_id)

    @router.post("/external-reviews", status_code=201)
    async def create(body: TranscriptCreate, profile_id: str = Depends(profile_exists)):
        return await call(service.create(profile_id, body.title, body.text))

    @router.post("/external-reviews/upload", status_code=201)
    async def upload(
        file: Annotated[UploadFile, Upload()], profile_id: str = Depends(profile_exists)
    ):
        title = Path(file.filename or "面试记录.txt").name
        if not title.lower().endswith(".txt"):
            raise HTTPException(422, "transcript_txt_required")
        raw = await file.read(800_001)
        if len(raw) > 800_000:
            raise HTTPException(413, "transcript_text_size")
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(422, "transcript_encoding")
        return await call(service.create(profile_id, title[:200], text, raw))

    @router.get("/external-review-samples")
    async def samples(profile_id: str = Depends(profile_exists)):
        return await service.samples()

    @router.post("/external-review-samples/{sample_id}", status_code=201)
    async def sample(sample_id: str, profile_id: str = Depends(profile_exists)):
        return await call(service.import_sample(profile_id, sample_id))

    @router.get("/external-reviews/{rid}")
    async def detail(rid: str, profile_id: str = Depends(profile_exists)):
        return await call(service.get(profile_id, rid))

    @router.post("/external-reviews/{rid}/draft")
    async def draft(rid: str, body: TranscriptConfirm, profile_id: str = Depends(profile_exists)):
        return await call(service.save_draft(profile_id, rid, body))

    @router.post("/external-reviews/{rid}/split")
    async def split(rid: str, body: TranscriptSplit, profile_id: str = Depends(profile_exists)):
        return await call(service.split(profile_id, rid, body))

    @router.post("/external-reviews/{rid}/parse", status_code=202)
    async def parse(rid: str, body: TranscriptRevision, profile_id: str = Depends(profile_exists)):
        return await call(service.parse_unknown(profile_id, rid, body.revision))

    @router.post("/external-reviews/{rid}/confirm", status_code=202)
    async def confirm(rid: str, body: TranscriptConfirm, profile_id: str = Depends(profile_exists)):
        return await call(service.confirm(profile_id, rid, body))

    @router.post("/external-reviews/{rid}/retry", status_code=202)
    async def retry(rid: str, profile_id: str = Depends(profile_exists)):
        return await call(service.retry(profile_id, rid))

    @router.get("/external-reviews/{rid}/raw")
    async def raw(rid: str, profile_id: str = Depends(profile_exists)):
        record = await call(service.store.get(profile_id, rid))
        return Response(
            record["raw_bytes"],
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{rid}.txt"'},
        )

    @router.get("/external-reviews/{rid}/docx")
    async def docx(rid: str, request: Request, profile_id: str = Depends(profile_exists)):
        record = await call(service.get(profile_id, rid))
        profile = await service.database.require_profile(profile_id)
        try:
            content = export_review(record, profile["display_name"])
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        filename = quote(record["title"] + "复盘.docx", safe="")
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )

    return router
