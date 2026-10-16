"""Import manifest-selected project files into one local interview profile."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mianshi_agent.config import get_settings
from mianshi_agent.db import Database
from mianshi_agent.embeddings import OllamaEmbeddingClient
from mianshi_agent.repository_import import import_project, load_manifest
from mianshi_agent.service import ProfileService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--project",
        action="append",
        required=True,
        metavar="PROJECT_ID=ROOT",
        help="May be repeated for every project selected from the manifest.",
    )
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def parse_project_roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        project_id, separator, root = value.partition("=")
        if not separator or not project_id or not root:
            raise ValueError(f"invalid_project_mapping:{value}")
        roots[project_id] = Path(root).resolve()
    return roots


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    database = Database(settings.app_database_path)
    await database.initialize()
    await database.require_profile(args.profile_id)
    embeddings = OllamaEmbeddingClient(
        base_url=settings.memory_embedding_base_url,
        model=settings.memory_embedding_model,
        dimensions=settings.memory_embedding_dimensions,
        timeout=settings.embedding_timeout,
    )
    profiles = ProfileService(database, settings, embeddings)
    manifest = load_manifest(args.manifest.resolve())
    roots = parse_project_roots(args.project)
    reports = []
    for project in manifest["projects"]:
        project_id = project["project_id"]
        if project_id not in roots:
            continue
        print(f"importing project={project_id} files={len(project['files'])}", flush=True)
        report = await import_project(
            profile_id=args.profile_id,
            root=roots[project_id],
            project=project,
            database=database,
            profiles=profiles,
        )
        reports.append(report)
        indexed = sum(
            item["embedding_status"] in {"indexed", "not_requested"}
            for item in report["files"]
        )
        print(
            f"completed project={project_id} files={len(report['files'])} indexed={indexed}",
            flush=True,
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {"manifest_version": manifest["version"], "projects": reports},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"report={args.report.resolve()}", flush=True)


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
