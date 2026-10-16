"""Exercise configured models in a temporary profile, never in the personal runtime DB."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mianshi_agent.config import get_settings
from mianshi_agent.main import create_app
from mianshi_agent.schemas import (
    DeepStudyCreate,
    InterviewAnswerCreate,
    InterviewSessionCreate,
    RoleTargetCreate,
    TextSourceCreate,
)


async def main():
    with TemporaryDirectory(prefix="mianshi-smoke-") as folder:
        settings = get_settings().model_copy(
            update={
                "app_database_path": Path(folder) / "smoke.sqlite3",
                "app_data_dir": Path(folder),
            }
        )
        app = create_app(settings)
        await app.state.database.initialize()
        await app.state.database.create_profile("smoke", "开发验证")
        await app.state.profile_service.create_role_target(
            "smoke",
            RoleTargetCreate(
                title="Python 后端开发",
                jd_text="理解 asyncio 的取消、超时与资源清理。",
                competencies=["异步编程", "稳定性"],
            ),
        )
        source = await app.state.profile_service.ingest_text(
            "smoke",
            TextSourceCreate(
                kind="study_note",
                title="示例学习笔记",
                text="asyncio 的取消通过 CancelledError 传播，应在 finally 中清理资源，"
                "通常不吞掉取消异常。",
            ),
        )
        print(
            json.dumps({"stage": "import", "embedding": source.response.embedding_status}),
            flush=True,
        )
        started = await app.state.interview_service.start(
            "smoke",
            InterviewSessionCreate(
                max_prompts=1,
                focus="asyncio 取消与超时",
            ),
        )
        print(json.dumps({"stage": "question", "status": started.session.status}), flush=True)
        ended = await app.state.interview_service.answer(
            "smoke",
            started.session.session_id,
            InterviewAnswerCreate(
                request_id="smoke_answer_001",
                answer=(
                    "这是开发验证示例。我认为任务取消会抛出 CancelledError，但我会吞掉这个异常，"
                    "直接返回 None，让上层当作成功，不再继续传播。"
                ),
            ),
        )
        assert ended.session.status == "completed" and ended.session.review is not None
        print(
            json.dumps(
                {
                    "stage": "review",
                    "status": ended.session.status,
                    "grounded_learning_gaps": len(ended.session.review.knowledge_gaps),
                }
            ),
            flush=True,
        )
        study = await app.state.study_service.create(
            "smoke",
            DeepStudyCreate(
                topic="为什么通常不应吞掉 asyncio.CancelledError？",
                session_id=started.session.session_id,
            ),
        )
        assert study.sections and study.evidence
        print(
            json.dumps(
                {
                    "stage": "study",
                    "sections": len(study.sections),
                    "evidence": len(study.evidence),
                    "embedding": study.diagnostics.embedding_status,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
