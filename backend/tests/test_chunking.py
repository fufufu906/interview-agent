from mianshi_agent.chunking import estimate_tokens, split_code_document, split_document


def test_split_document_keeps_order_and_budget() -> None:
    text = "第一段介绍项目。" * 80 + "\n\n" + "Second paragraph about FastAPI." * 30
    chunks = split_document(text, max_tokens=80, overlap_tokens=8)

    assert len(chunks) > 1
    assert [item.ordinal for item in chunks] == list(range(len(chunks)))
    assert all(estimate_tokens(item.text) <= 90 for item in chunks)
    assert chunks[0].locator == {"kind": "paragraph", "index": 1}


def test_split_code_document_preserves_line_ranges() -> None:
    chunks = split_code_document(
        "\n".join(f"line_{index}" for index in range(1, 31)),
        max_lines=12,
        overlap_lines=2,
    )

    assert len(chunks) == 3
    assert chunks[0].locator == {"kind": "line_range", "line_start": 1, "line_end": 12}
    assert chunks[1].locator["line_start"] == 11
    assert chunks[-1].locator["line_end"] == 30
