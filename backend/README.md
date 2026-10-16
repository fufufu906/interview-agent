# Interview Agent Backend

FastAPI API for profile-scoped evidence retrieval, strict interview simulation, post-session review and suggested answers.

From this directory:

```bash
cp .env.example .env
# Fill LLM_BASE_URL, LLM_API_KEY and LLM_MODEL_ID locally.
uv sync --all-groups
uv run uvicorn mianshi_agent.main:app --host 127.0.0.1 --port 8000
```

Use one worker. Runtime data is stored under ../data/runtime and is ignored by Git. Model errors preserve submitted answers; retry resumes the pending question or review. Suggested answers are generated only after the interview ends.

API reference: http://127.0.0.1:8000/docs . Architecture and data boundaries: [architecture](../docs/architecture.md).

```bash
uv run ruff check src tests
uv run pytest -q
```

Optional scripts under scripts/ support profile bootstrap and selected repository evidence import. Use your own local files and an explicitly reviewed manifest; config/project-evidence-manifest.example.json is an empty-content example. Do not commit filled profiles, provider credentials or import reports.
