from pathlib import Path

from mianshi_agent.repository_import import capture_snapshot, extract_symbols


def test_non_git_snapshot_is_stable_for_selected_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    first = capture_snapshot(tmp_path, ["a.py"])
    second = capture_snapshot(tmp_path, ["a.py"])

    assert first.git_head is None
    assert first.revision == second.revision
    assert first.revision.startswith("files:")


def test_extract_symbols_keeps_source_lines() -> None:
    python_symbols = extract_symbols(
        "service.py",
        "class Worker:\n    async def run(self):\n        return None\n",
    )
    java_symbols = extract_symbols(
        "Worker.java",
        "public class Worker {\n    public String run() { return \"ok\"; }\n}\n",
    )

    assert {item["name"] for item in python_symbols} == {"Worker", "run"}
    assert any(item["name"] == "Worker" and item["line"] == 1 for item in java_symbols)
    assert any(item["name"] == "run" and item["line"] == 2 for item in java_symbols)
