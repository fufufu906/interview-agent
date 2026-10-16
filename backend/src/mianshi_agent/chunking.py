"""Structure-aware document chunking for mixed Chinese and Latin text."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_CJK = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True, slots=True)
class TextChunk:
    """One stable ordered chunk with a human-readable locator."""

    ordinal: int
    text: str
    locator: dict[str, int | str]


def estimate_tokens(text: str) -> int:
    """Estimate mixed Chinese and Latin tokens without a tokenizer dependency."""
    cjk = len(_CJK.findall(text))
    remaining = len(_CJK.sub("", text).replace(" ", "").replace("\n", ""))
    return cjk + math.ceil(remaining / 4)


def _prefix_index(text: str, token_budget: int) -> int:
    cost = 0.0
    for index, char in enumerate(text):
        if char.isspace():
            continue
        cost += 1.0 if _CJK.fullmatch(char) else 0.25
        if cost >= token_budget:
            return index + 1
    return len(text)


def _blocks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]


def split_document(
    text: str,
    *,
    max_tokens: int = 420,
    overlap_tokens: int = 48,
    locator_prefix: str = "paragraph",
) -> list[TextChunk]:
    """Split at paragraph boundaries and retain bounded overlap."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be between zero and max_tokens")

    atoms: list[str] = []
    for block in _blocks(text):
        remainder = block
        while estimate_tokens(remainder) > max_tokens:
            cut = _prefix_index(remainder, max_tokens)
            atoms.append(remainder[:cut].strip())
            remainder = remainder[cut:].strip()
        if remainder:
            atoms.append(remainder)

    chunks: list[str] = []
    current = ""
    for atom in atoms:
        combined = f"{current}\n\n{atom}".strip() if current else atom
        if current and estimate_tokens(combined) > max_tokens:
            chunks.append(current)
            overlap = ""
            if overlap_tokens:
                reversed_cut = _prefix_index(current[::-1], overlap_tokens)
                overlap = current[max(0, len(current) - reversed_cut) :].strip()
            current = f"{overlap}\n\n{atom}".strip() if overlap else atom
        else:
            current = combined
    if current:
        chunks.append(current)

    return [
        TextChunk(
            ordinal=index,
            text=chunk,
            locator={"kind": locator_prefix, "index": index + 1},
        )
        for index, chunk in enumerate(chunks)
    ]


def split_code_document(
    text: str,
    *,
    max_lines: int = 100,
    overlap_lines: int = 12,
    max_tokens: int = 900,
) -> list[TextChunk]:
    """Split source code by line range so evidence keeps file locations."""
    if max_lines <= 0 or max_tokens <= 0:
        raise ValueError("max_lines and max_tokens must be positive")
    if overlap_lines < 0 or overlap_lines >= max_lines:
        raise ValueError("overlap_lines must be between zero and max_lines")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    if not lines:
        return []
    chunks: list[TextChunk] = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + max_lines)
        while end > start + 1 and estimate_tokens("\n".join(lines[start:end])) > max_tokens:
            end -= 1
        chunk_text = "\n".join(lines[start:end]).strip()
        if chunk_text:
            chunks.append(
                TextChunk(
                    ordinal=len(chunks),
                    text=chunk_text,
                    locator={
                        "kind": "line_range",
                        "line_start": start + 1,
                        "line_end": end,
                    },
                )
            )
        if end >= len(lines):
            break
        start = max(start + 1, end - overlap_lines)
    return chunks
