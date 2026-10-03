from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article, ArticleVersion
from app.models.publisher_worker import PublisherWorkerJob
from app.models.runtime import ArticleRun, Job
from app.services.native_publishers import _run_browser_runner_publisher
from app.services.publisher_worker_queue import (
    claim_next_publisher_worker_job,
    complete_publisher_worker_job,
    enqueue_publisher_worker_job,
)


def test_publisher_worker_queue_claims_and_completes_job(db_session_factory: sessionmaker[Session]) -> None:
    with db_session_factory() as db:
        article = Article(seed_title="TS worker", confirmed_title="TS worker")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        parent_job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(parent_job)
        db.flush()

        worker_job = enqueue_publisher_worker_job(
            db,
            parent_job=parent_job,
            platform="CSDN",
            action="prepare-article",
            payload={"title": "TS worker"},
            artifact_json={"payload_json": "/tmp/payload.json"},
            timeout_seconds=120,
        )
        db.commit()

        claimed = claim_next_publisher_worker_job(db, worker_id="publisher-worker-test")
        assert claimed is not None
        assert claimed.id == worker_job.id
        assert claimed.status == "running"
        assert claimed.claimed_by == "publisher-worker-test"
        assert claimed.attempt_count == 1

        complete_publisher_worker_job(
            db,
            worker_job=claimed,
            result={"status": "ok", "public_url": "https://example.com/csdn"},
        )
        db.commit()

        stored = db.get(PublisherWorkerJob, worker_job.id)
        assert stored is not None
        assert stored.status == "succeeded"
        assert stored.result_json["public_url"] == "https://example.com/csdn"
        assert stored.finished_at is not None


def test_complete_publisher_worker_job_marks_session_invalid_waiting_for_human(db_session_factory: sessionmaker[Session]) -> None:
    with db_session_factory() as db:
        article = Article(seed_title="InfoQ login", confirmed_title="InfoQ login")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        parent_job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(parent_job)
        db.flush()
        worker_job = enqueue_publisher_worker_job(
            db,
            parent_job=parent_job,
            platform="InfoQ",
            action="prepare-article",
            payload={"title": "InfoQ login"},
            artifact_json={"payload_json": "/tmp/payload.json"},
            timeout_seconds=120,
        )
        claimed = claim_next_publisher_worker_job(db, worker_id="publisher-worker-test")
        assert claimed is not None
        complete_publisher_worker_job(
            db,
            worker_job=claimed,
            result={
                "status": "blocked",
                "reason": "session_invalid_or_missing",
                "final_url": "https://xie.infoq.cn/write",
            },
        )
        db.commit()
        stored = db.get(PublisherWorkerJob, worker_job.id)
        assert stored is not None
        assert stored.status == "waiting_for_human"
        assert stored.failure_code == "session_invalid_or_missing"
        assert stored.result_json["status"] == "blocked"


def test_browser_publisher_hands_off_to_publisher_worker_without_python_subprocess(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    called_subprocess = False

    def forbidden_subprocess(*_args, **_kwargs):
        nonlocal called_subprocess
        called_subprocess = True
        raise AssertionError("Python must not execute Node browser runner subprocesses")

    monkeypatch.setattr("app.services.native_publishers.subprocess.run", forbidden_subprocess)

    def fake_wait(db, *, worker_job, timeout_seconds, poll_interval_seconds=2.0):
        del db, timeout_seconds, poll_interval_seconds
        return {
            "status": "ok",
            "published_article_url": f"https://example.com/{worker_job.platform}",
            "verified": True,
            "http_status": 200,
        }

    monkeypatch.setattr("app.services.native_publishers.wait_for_publisher_worker_job", fake_wait)

    with db_session_factory() as db:
        article = Article(
            seed_title="Worker handoff",
            confirmed_title="Worker handoff final",
            summary="Postgres summary.",
            metadata_json={"tags": ["AImagician"]},
        )
        db.add(article)
        db.flush()
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown="## 正文\n\n来自 Postgres。",
            is_current=True,
        )
        db.add(version)
        db.flush()
        article.current_version_id = version.id
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        parent_job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(parent_job)
        db.flush()

        result = _run_browser_runner_publisher(parent_job, platform="CSDN", matrix_child=True)

        worker_jobs = db.execute(
            select(PublisherWorkerJob).where(PublisherWorkerJob.parent_job_id == parent_job.id)
        ).scalars().all()

    assert called_subprocess is False
    assert result["status"] == "ok"
    assert result["publisher_mode"] == "publisher_worker"
    assert result["public_url"] == "https://example.com/CSDN"
    assert len(worker_jobs) == 1
    assert worker_jobs[0].platform == "CSDN"
    assert worker_jobs[0].payload_json["title"] == "Worker handoff final"
    assert worker_jobs[0].artifact_json["publisher_worker_contract"] == "postgres_claimed_ts_worker"
