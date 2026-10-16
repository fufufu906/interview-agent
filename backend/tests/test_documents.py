import pytest

from mianshi_agent.documents import DocumentExtractionError, extract_document_text


def test_text_documents_support_utf8_and_gb18030() -> None:
    expected = "向量检索测试"
    assert extract_document_text("notes.md", expected.encode("utf-8")) == expected
    assert extract_document_text("notes.txt", expected.encode("gb18030")) == expected


def test_unknown_document_type_is_rejected() -> None:
    with pytest.raises(DocumentExtractionError, match="unsupported_file_type"):
        extract_document_text("resume.doc", b"not-a-supported-document")
