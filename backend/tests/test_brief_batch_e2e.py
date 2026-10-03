from datetime import date, datetime, timezone
from uuid import uuid4

from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.brief_batch import ContentOutput
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job
from app.services.brief_batches import (
    auto_confirm_daily_brief_batch,
    create_brief_wechat_drafts,
    get_daily_brief_batch_observability,
    start_or_resume_daily_brief_batch,
)


def candidate(rank: int) -> dict[str, object]:
    return {
        "cluster_key": f"cluster-{rank}",
        "score": 100 - rank,
        "published_at": datetime(2026, 8, 14, tzinfo=timezone.utc),
        "title": f"Topic {rank}",
        "summary": f"Summary {rank}",
        "canonical_source": f"https://example.test/{rank}",
        "evidence": [],
    }


def make_publishable(db, article_id) -> None:
    version = ArticleVersion(
        article_id=article_id,
        version_number=1,
        version_kind="generate_article_body",
        body_html='<article><header class="wx-brief-header"><h1>Brief</h1></header><section class="wx-brief-sources">Source</section></article>',
        is_current=True,
    )
    db.add(version)
    db.flush()
    article = db.get(Article, article_id)
    assert article is not None
    article.current_version_id = version.id
    db.add(ArticleAsset(article_id=article_id, asset_type="cover", role="selected_cover", local_path="/tmp/selected-cover.png"))
    run = db.query(ArticleRun).filter_by(article_id=article_id, run_type="article_flow").one()
    run.current_stage = "wechat_draft_preview_ready"
    run.status = "waiting_for_input"
    db.flush()


def test_daily_brief_auto_confirm_and_draft_resume_are_safe_and_idempotent(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 14), [candidate(rank) for rank in range(1, 9)])
        confirmed = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        dry_run = create_brief_wechat_drafts(db, batch_id=result.batch_id)

        assert confirmed["batch"]["status"] == "awaiting_drafts"
        assert [output["status"] for output in confirmed["outputs"]] == ["awaiting_drafts"] * 3
        assert dry_run["intended_actions"] == []
        assert [item["slot"] for item in dry_run["skipped"]] == ["rank_1", "rank_2", "rank_3"]

        rank_1 = next(output for output in result.outputs if output.slot == "rank_1")
        db.add(ArticlePlatformPublication(article_id=rank_1.article_id, platform="公众号", status="draft_created", draft_id="draft-rank-1"))
        for output in result.outputs:
            if output.slot != "rank_1":
                make_publishable(db, output.article_id)
        db.flush()
        queued = create_brief_wechat_drafts(db, batch_id=result.batch_id, dry_run=False)
        assert queued["queued"] == ["rank_2", "rank_3"]
        assert queued["completed"] == []
        assert len(db.query(Article).all()) == 3
        assert len(db.query(ArticlePlatformPublication).all()) == 3

        observability = get_daily_brief_batch_observability(db, batch_id=result.batch_id)
        assert [item["rank"] for item in observability["snapshot"]["items"]] == list(range(1, 9))
        assert [output["snapshot_item_ids"] for output in observability["outputs"]] == [
            [str(result.snapshot_items[0].id)],
            [str(result.snapshot_items[1].id)],
            [str(result.snapshot_items[2].id)],
        ]


def test_daily_brief_non_dry_run_enqueues_one_wechat_job_per_unfinished_output(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 15), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        for output in result.outputs:
            make_publishable(db, output.article_id)

        first = create_brief_wechat_drafts(db, batch_id=result.batch_id, dry_run=False)
        second = create_brief_wechat_drafts(db, batch_id=result.batch_id, dry_run=False)

        assert first["completed"] == []
        assert first["queued"] == ["rank_1", "rank_2", "rank_3"]
        assert first["failed"] == []
        assert first["batch"]["status"] == "awaiting_drafts"
        assert second["completed"] == []
        assert second["queued"] == ["rank_1", "rank_2", "rank_3"]
        assert len(db.query(ArticleRun).filter_by(run_type="article_flow").all()) == 3
        jobs = db.query(Job).filter_by(job_type="publish_wechat_draft").all()
        assert len(jobs) == 3
        assert {job.job_type for job in jobs} == {"publish_wechat_draft"}
        assert {job.status for job in jobs} == {"queued"}
        publications = db.query(ArticlePlatformPublication).all()
        assert len(publications) == 3
        assert {publication.platform for publication in publications} == {"公众号"}
        assert {publication.status for publication in publications} == {"queued"}


def test_daily_brief_prepare_starts_one_auto_confirmed_flow_per_output(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 16), [candidate(rank) for rank in range(1, 9)])

        prepared = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        assert prepared["started_flow_slots"] == ["rank_1", "rank_2", "rank_3"]
        runs = db.query(ArticleRun).filter_by(run_type="article_flow").all()
        assert len(runs) == 3
        assert {run.current_stage for run in runs} == {"research_queued"}
        assert {job.job_type for job in db.query(Job).all()} == {"deep_research"}


def test_daily_brief_refuses_draft_queue_for_invalid_current_body(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 17), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        output = result.outputs[0]
        article = db.get(Article, output.article_id)
        assert article is not None
        article.current_version_id = uuid4()
        db.add(ArticleAsset(article_id=article.id, asset_type="cover", role="selected_cover", local_path="/tmp/selected-cover.png"))
        db.flush()

        queued = create_brief_wechat_drafts(db, batch_id=result.batch_id, dry_run=False)

        assert queued["queued"] == []
        assert queued["failed"] == []
        assert queued["skipped"][0]["slot"] == "rank_1"
        assert db.query(Job).filter_by(job_type="publish_wechat_draft").count() == 0


def test_daily_brief_prepare_advances_one_legal_step_after_completed_job(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 18), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        research_jobs = db.query(Job).filter_by(job_type="deep_research").all()
        for job in research_jobs:
            job.status = "succeeded"
        db.flush()

        first_advance = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        assert first_advance["advanced_flow_slots"] == ["rank_1", "rank_2", "rank_3"]
        assert db.query(Job).filter_by(job_type="generate_title_outline_preview").count() == 3
        for job in db.query(Job).filter_by(job_type="generate_title_outline_preview").all():
            job.status = "succeeded"
        db.flush()

        second_advance = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        assert second_advance["advanced_flow_slots"] == ["rank_1", "rank_2", "rank_3"]
        runs = db.query(ArticleRun).filter_by(run_type="article_flow").all()
        assert {run.current_stage for run in runs} == {"ready_for_article_generation"}


def test_daily_brief_prepare_retries_a_failed_cover_render_job(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 19), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        output = result.outputs[0]
        run = db.query(ArticleRun).filter_by(article_id=output.article_id, run_type="article_flow").one()
        output_row = db.query(ContentOutput).filter_by(article_id=output.article_id).one()
        run.current_stage = "cover_candidates_queued"
        run.status = "blocked"
        db.add(Job(run_id=run.id, article_id=output.article_id, job_type="render_cover_candidates", status="failed", idempotency_key=f"brief:{output_row.id}:render_cover_candidates"))
        db.flush()

        prepared = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        assert "rank_1" in prepared["advanced_flow_slots"]
        retries = db.query(Job).filter_by(run_id=run.id, job_type="render_cover_candidates").all()
        assert {job.status for job in retries} == {"superseded", "queued"}
        retry = next(job for job in retries if job.status == "queued")
        assert retry.input_json["candidate_count"] == 1


def test_daily_brief_prepare_retries_a_failed_body_job(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 20), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        output = result.outputs[0]
        output_row = db.query(ContentOutput).filter_by(article_id=output.article_id).one()
        run = db.query(ArticleRun).filter_by(article_id=output.article_id, run_type="article_flow").one()
        run.current_stage = "article_generation_queued"
        run.status = "blocked"
        db.add(Job(run_id=run.id, article_id=output.article_id, job_type="generate_article_body", status="failed", idempotency_key=f"brief:{output_row.id}:generate_article_body"))
        db.flush()

        prepared = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        assert "rank_1" in prepared["advanced_flow_slots"]
        retries = db.query(Job).filter_by(run_id=run.id, job_type="generate_article_body").all()
        assert {job.status for job in retries} == {"superseded", "queued"}


def test_daily_brief_body_generation_uses_headroom_without_lowering_confirmed_floor(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 21), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        for output in result.outputs:
            run = db.query(ArticleRun).filter_by(article_id=output.article_id, run_type="article_flow").one()
            run.current_stage = "cover_selected"
            run.status = "waiting_for_input"
        db.flush()

        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        jobs = {job.article_id: job for job in db.query(Job).filter_by(job_type="generate_article_body").all()}
        rank_1 = result.outputs[0]
        rank_2 = result.outputs[1]
        assert jobs[rank_1.article_id].input_json["confirmed_target_word_count"] == 800
        assert jobs[rank_1.article_id].input_json["effective_generation_target_word_count"] == 1000
        assert jobs[rank_2.article_id].input_json["confirmed_target_word_count"] == 800
        assert jobs[rank_2.article_id].input_json["effective_generation_target_word_count"] == 1000


def test_daily_brief_first_cover_render_requests_single_candidate(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 22), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        for output in result.outputs:
            run = db.query(ArticleRun).filter_by(article_id=output.article_id, run_type="article_flow").one()
            run.current_stage = "cover_visual_brief_confirmed"
            run.status = "waiting_for_input"
        db.flush()

        prepared = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        assert prepared["advanced_flow_slots"] == ["rank_1", "rank_2", "rank_3"]
        jobs = db.query(Job).filter_by(job_type="render_cover_candidates").all()
        assert len(jobs) == 3
        assert {job.input_json.get("candidate_count") for job in jobs} == {1}


def test_daily_brief_create_drafts_skips_outputs_that_are_not_ready(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 23), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        queued = create_brief_wechat_drafts(db, batch_id=result.batch_id, dry_run=False)

        assert queued["queued"] == []
        assert queued["completed"] == []
        assert queued["failed"] == []
        assert [item["slot"] for item in queued["skipped"]] == ["rank_1", "rank_2", "rank_3"]
        assert queued["batch"]["status"] == "awaiting_drafts"
        assert db.query(Job).filter_by(job_type="publish_wechat_draft").count() == 0


def test_daily_brief_create_drafts_marks_batch_ready_when_all_drafts_already_exist(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 24), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        for output in result.outputs:
            db.add(ArticlePlatformPublication(article_id=output.article_id, platform="公众号", status="draft_created", draft_id=f"draft-{output.slot}"))
        db.flush()

        queued = create_brief_wechat_drafts(db, batch_id=result.batch_id, dry_run=False)

        assert queued["intended_actions"] == []
        assert queued["skipped"] == []
        assert queued["failed"] == []
        assert queued["batch"]["status"] == "drafts_ready"


def test_daily_brief_skips_wechat_draft_while_preview_job_is_queued(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 25), [candidate(rank) for rank in range(1, 9)])
        auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
        for output in result.outputs:
            make_publishable(db, output.article_id)
            run = db.query(ArticleRun).filter_by(article_id=output.article_id, run_type="article_flow").one()
            run.current_stage = "wechat_draft_preview_queued"
            run.status = "running"
        db.flush()

        queued = create_brief_wechat_drafts(db, batch_id=result.batch_id, dry_run=False)

        assert queued["queued"] == []
        assert queued["completed"] == []
        assert queued["failed"] == []
        assert [item["slot"] for item in queued["skipped"]] == ["rank_1", "rank_2", "rank_3"]
        assert {item["reason"] for item in queued["skipped"]} == {"not_ready_for_wechat_draft"}
        assert db.query(Job).filter_by(job_type="publish_wechat_draft").count() == 0


def test_legacy_digest_slot_is_ignored_when_confirming_and_drafting(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 26), [candidate(rank) for rank in range(1, 9)])
        leftover = Article(
            source_kind="brief_batch",
            source_ref="article:output:digest",
            seed_title="8月26日早报：今日技术热点",
            confirmed_title="8月26日早报：今日技术热点",
            content_mode_key="morning_digest",
        )
        db.add(
            ContentOutput(
                batch_id=result.batch_id,
                article=leftover,
                slot="digest",
                snapshot_item_ids=[str(item.id) for item in result.snapshot_items[:3]],
            )
        )
        db.flush()

        confirmed = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)

        assert confirmed["started_flow_slots"] == ["rank_1", "rank_2", "rank_3"]
        assert [output["slot"] for output in confirmed["outputs"]] == ["rank_1", "rank_2", "rank_3"]
        runs = db.query(ArticleRun).filter_by(run_type="article_flow").all()
        assert len(runs) == 3
        assert leftover.id not in {run.article_id for run in runs}
