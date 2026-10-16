"""Targeted, read-only repository evidence import with reproducible provenance."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mianshi_agent.db import Database, utcnow_iso
from mianshi_agent.schemas import TextSourceCreate
from mianshi_agent.service import ProfileService

CODE_SUFFIXES = {".py", ".java", ".js", ".jsx", ".ts", ".tsx", ".vue"}


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """Describe the exact selected working-tree material observed during import."""

    revision: str
    git_head: str | None
    dirty: bool
    file_hashes: dict[str, str]


def load_manifest(path: Path) -> dict[str, Any]:
    """Load the committed, reviewable targeted-file selection."""
    return json.loads(path.read_text(encoding="utf-8"))


def read_source_file(path: Path) -> str:
    """Read a selected source file without changing it."""
    content = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.strip():
            return text
    raise ValueError(f"unreadable_or_empty_file:{path}")


def capture_snapshot(root: Path, relative_paths: list[str]) -> RepositorySnapshot:
    """Hash selected files and bind them to Git HEAD when available."""
    file_hashes = {
        relative_path: hashlib.sha256(
            (root / Path(relative_path)).read_bytes()
        ).hexdigest()
        for relative_path in relative_paths
    }
    git_head = _git_output(root, ["rev-parse", "HEAD"])
    if git_head:
        status = _git_output(
            root,
            ["status", "--porcelain", "--untracked-files=all", "--", *relative_paths],
        )
        dirty = bool(status.strip())
        revision = f"git:{git_head}:{'dirty' if dirty else 'clean'}"
    else:
        dirty = False
        joined = "\n".join(f"{path}:{digest}" for path, digest in file_hashes.items())
        revision = f"files:{hashlib.sha256(joined.encode()).hexdigest()}"
    return RepositorySnapshot(
        revision=revision,
        git_head=git_head or None,
        dirty=dirty,
        file_hashes=file_hashes,
    )


async def import_project(
    *,
    profile_id: str,
    root: Path,
    project: dict[str, Any],
    database: Database,
    profiles: ProfileService,
) -> dict[str, Any]:
    """Import only manifest-selected files and build a small code evidence graph."""
    root = root.resolve()
    selections = project["files"]
    relative_paths = [item["path"].replace("\\", "/") for item in selections]
    missing = [path for path in relative_paths if not (root / Path(path)).is_file()]
    if missing:
        raise FileNotFoundError(f"missing_selected_files:{missing}")
    snapshot = capture_snapshot(root, relative_paths)
    imported: list[dict[str, Any]] = []
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    created_at = utcnow_iso()
    project_node_id = _stable_id("project", profile_id, project["project_id"])
    first_chunk_id: str | None = None

    for selection, relative_path in zip(selections, relative_paths, strict=True):
        source_path = root / Path(relative_path)
        text = read_source_file(source_path)
        suffix = source_path.suffix.lower()
        origin_uri = f"project://{project['project_id']}/{relative_path}"
        result = await profiles.ingest_text(
            profile_id,
            TextSourceCreate(
                kind="project_repository",
                title=f"{project['name']} · {relative_path}",
                text=text,
                origin_uri=origin_uri,
                metadata={
                    "project_id": project["project_id"],
                    "folder_root": str(root),
                    "relative_path": relative_path,
                    "local_path": str(source_path),
                    "snapshot_revision": snapshot.revision,
                    "file_sha256": snapshot.file_hashes[relative_path],
                    "claims": selection["claims"],
                    "content_format": "code" if suffix in CODE_SUFFIXES else "document",
                    "replace_origin": True,
                    "provenance": "code_observed_not_contribution_proof",
                },
            ),
        )
        chunks = [
            item
            for item in await database.list_chunks(profile_id)
            if item["source_id"] == result.response.source_id
        ]
        if chunks and first_chunk_id is None:
            first_chunk_id = chunks[0]["chunk_id"]
        document_node_id = f"document_{result.response.source_id}"
        graph_edges.append(
            _edge(
                profile_id,
                project_node_id,
                document_node_id,
                "contains",
                created_at,
                chunks[0]["chunk_id"] if chunks else None,
            )
        )
        symbols = extract_symbols(relative_path, text)
        for symbol in symbols:
            chunk_id = _chunk_for_line(chunks, symbol["line"])
            symbol_node_id = _stable_id(
                "symbol",
                project["project_id"],
                relative_path,
                symbol["kind"],
                symbol["name"],
                str(symbol["line"]),
            )
            graph_nodes.append(
                {
                    "node_id": symbol_node_id,
                    "profile_id": profile_id,
                    "node_type": "code_symbol",
                    "name": symbol["name"],
                    "description": f"{relative_path}:{symbol['line']} {symbol['kind']}",
                    "source_chunk_id": chunk_id,
                    "verification_status": "code_observed",
                    "metadata": {
                        "project_id": project["project_id"],
                        "relative_path": relative_path,
                        **symbol,
                    },
                    "created_at": created_at,
                }
            )
            graph_edges.append(
                _edge(
                    profile_id,
                    document_node_id,
                    symbol_node_id,
                    "defines",
                    created_at,
                    chunk_id,
                )
            )
        imported.append(
            {
                "relative_path": relative_path,
                "source_id": result.response.source_id,
                "file_sha256": snapshot.file_hashes[relative_path],
                "chunk_count": result.response.chunk_count,
                "embedding_status": result.response.embedding_status,
                "deduplicated": result.deduplicated,
                "claims": selection["claims"],
                "symbol_count": len(symbols),
            }
        )

    graph_nodes.insert(
        0,
        {
            "node_id": project_node_id,
            "profile_id": profile_id,
            "node_type": "project",
            "name": project["name"],
            "description": "定向代码证据；不自动证明个人贡献或运行指标。",
            "source_chunk_id": first_chunk_id,
            "verification_status": "code_observed",
            "metadata": {
                "project_id": project["project_id"],
                "snapshot_revision": snapshot.revision,
                "selected_file_count": len(imported),
            },
            "created_at": created_at,
        },
    )
    for competency in project.get("competencies", []):
        competency_digest = hashlib.sha256(
            f"{profile_id}:{competency}".encode()
        ).hexdigest()
        competency_node_id = f"competency_{competency_digest[:24]}"
        graph_nodes.append(
            {
                "node_id": competency_node_id,
                "profile_id": profile_id,
                "node_type": "competency",
                "name": competency,
                "description": "",
                "source_chunk_id": None,
                "verification_status": "user_supplied",
                "metadata": {},
                "created_at": created_at,
            }
        )
        graph_edges.append(
            _edge(
                profile_id,
                project_node_id,
                competency_node_id,
                "relevant_to",
                created_at,
                first_chunk_id,
            )
        )
    await database.create_graph_nodes_and_edges(graph_nodes, graph_edges)
    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "root": str(root),
        "snapshot": {
            "revision": snapshot.revision,
            "git_head": snapshot.git_head,
            "dirty": snapshot.dirty,
        },
        "files": imported,
        "imported_at": datetime.now(UTC).isoformat(),
    }


def extract_symbols(relative_path: str, text: str) -> list[dict[str, Any]]:
    """Extract navigational symbols without claiming full semantic analysis."""
    suffix = Path(relative_path).suffix.lower()
    if suffix == ".py":
        return _python_symbols(text)
    if suffix == ".java":
        return _regex_symbols(
            text,
            [
                ("type", r"\b(?:class|interface|record|enum)\s+([A-Za-z_]\w*)"),
                (
                    "method",
                    r"^\s*(?:public|protected|private)\s+(?:static\s+)?"
                    r"[\w<>, ?\[\].]+\s+([A-Za-z_]\w*)\s*\(",
                ),
            ],
        )
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return _regex_symbols(
            text,
            [
                ("class", r"\bclass\s+([A-Za-z_$][\w$]*)"),
                ("function", r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
                (
                    "function",
                    r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
                ),
            ],
        )
    return []


def _python_symbols(text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append({"kind": "class", "name": node.name, "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                {
                    "kind": "function",
                    "name": node.name,
                    "line": node.lineno,
                }
            )
    return sorted(symbols, key=lambda item: (item["line"], item["name"]))


def _regex_symbols(
    text: str, patterns: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE):
            symbols.append(
                {
                    "kind": kind,
                    "name": match.group(1),
                    "line": text.count("\n", 0, match.start()) + 1,
                }
            )
    unique = {(item["kind"], item["name"], item["line"]): item for item in symbols}
    return sorted(unique.values(), key=lambda item: (item["line"], item["name"]))


def _chunk_for_line(chunks: list[dict[str, Any]], line: int) -> str | None:
    for chunk in chunks:
        locator = chunk["locator"]
        if (
            locator.get("kind") == "line_range"
            and locator.get("line_start", 0) <= line <= locator.get("line_end", 0)
        ):
            return chunk["chunk_id"]
    return chunks[0]["chunk_id"] if chunks else None


def _edge(
    profile_id: str,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    created_at: str,
    source_chunk_id: str | None,
) -> dict[str, Any]:
    return {
        "edge_id": _stable_id("edge", source_node_id, target_node_id, edge_type),
        "profile_id": profile_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "edge_type": edge_type,
        "weight": 1.0,
        "source_chunk_id": source_chunk_id,
        "verification_status": "code_observed",
        "created_at": created_at,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _git_output(root: Path, arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""
