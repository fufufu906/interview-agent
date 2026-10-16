"""Bootstrap one local interview profile from a resume and a target-role file."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from mianshi_agent.config import get_settings
from mianshi_agent.db import Database
from mianshi_agent.documents import extract_document_text
from mianshi_agent.embeddings import OllamaEmbeddingClient
from mianshi_agent.schemas import RoleTargetCreate, TextSourceCreate
from mianshi_agent.service import ProfileService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--resume", required=True, type=Path)
    parser.add_argument("--jd", required=True, type=Path)
    parser.add_argument("--role-title", required=True)
    parser.add_argument("--company", default="")
    parser.add_argument("--level", default="")
    parser.add_argument("--competency", action="append", default=[])
    return parser.parse_args()


async def bootstrap(args: argparse.Namespace) -> None:
    settings = get_settings()
    database = Database(settings.app_database_path)
    await database.initialize()
    embeddings = OllamaEmbeddingClient(
        base_url=settings.memory_embedding_base_url,
        model=settings.memory_embedding_model,
        dimensions=settings.memory_embedding_dimensions,
        timeout=settings.embedding_timeout,
    )
    service = ProfileService(database, settings, embeddings)

    await database.create_profile(args.profile_id, args.display_name)
    resume_text = extract_document_text(args.resume.name, args.resume.read_bytes())
    resume_result = await service.ingest_text(
        args.profile_id,
        TextSourceCreate(
            kind="resume",
            title=f"{args.display_name}的简历",
            text=resume_text,
            origin_uri=str(args.resume.resolve()),
            metadata={"filename": args.resume.name},
        ),
    )
    role = await service.create_role_target(
        args.profile_id,
        RoleTargetCreate(
            title=args.role_title,
            company=args.company,
            level=args.level,
            jd_text=args.jd.read_text(encoding="utf-8"),
            competencies=args.competency,
            activate=True,
        ),
    )
    print(
        f"profile={args.profile_id} "
        f"resume_source={resume_result.response.source_id} "
        f"resume_embedding={resume_result.response.embedding_status} "
        f"role={role.role_target_id}"
    )


if __name__ == "__main__":
    asyncio.run(bootstrap(parse_args()))
