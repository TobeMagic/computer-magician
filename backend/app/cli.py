import argparse
import json

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.admin_bootstrap import bootstrap_admin
from app.services.deployment_doctor import run_deployment_doctor
from app.services.prompt_snapshots import backfill_prompt_snapshots
from app.services.script_adapter import ScriptAdapterError, describe_next_script_job, execute_next_script_job, run_worker_loop
from app.services.worker import claim_next_job


def main() -> None:
    parser = argparse.ArgumentParser(description="AImagician backend administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap-admin", help="Create or update the single admin user")
    bootstrap_parser.add_argument("--email")
    bootstrap_parser.add_argument("--display-name")
    bootstrap_parser.add_argument("--password")
    bootstrap_parser.add_argument("--rotate-password", action="store_true")

    worker_claim_parser = subparsers.add_parser("worker-claim", help="Claim one queued job for smoke testing")
    worker_claim_parser.add_argument("--worker-id", default="local-worker")

    worker_run_parser = subparsers.add_parser("worker-run-once", help="Claim and execute one approved script job")
    worker_run_parser.add_argument("--worker-id", default="local-worker")
    worker_run_parser.add_argument("--dry-run", action="store_true", help="Describe the next job without claiming or executing it")

    worker_loop_parser = subparsers.add_parser("worker-loop", help="Continuously execute approved script jobs")
    worker_loop_parser.add_argument("--worker-id", default="local-worker")
    worker_loop_parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    worker_loop_parser.add_argument("--max-jobs", type=int, default=0, help="Stop after N jobs; 0 means unlimited")
    worker_loop_parser.add_argument("--max-idle-seconds", type=float, default=0.0, help="Stop after idle seconds; 0 means unlimited")

    doctor_parser = subparsers.add_parser("doctor", help="Run private-server deployment diagnostics")
    doctor_parser.add_argument("--fail-on-error", action="store_true", help="Exit non-zero when any check is error")
    doctor_parser.add_argument(
        "--no-create-artifact-root",
        action="store_true",
        help="Do not create AIMAGICIAN_ARTIFACT_ROOT while checking writability",
    )

    snapshot_backfill_parser = subparsers.add_parser("prompt-snapshot-backfill", help="Backfill rendered prompt snapshots from succeeded native jobs")
    snapshot_backfill_parser.add_argument("--limit", type=int, default=0)

    args = parser.parse_args()
    if args.command == "bootstrap-admin":
        _bootstrap_admin(args)
    elif args.command == "worker-claim":
        _worker_claim(args)
    elif args.command == "worker-run-once":
        _worker_run_once(args)
    elif args.command == "worker-loop":
        _worker_loop(args)
    elif args.command == "doctor":
        _doctor(args)
    elif args.command == "prompt-snapshot-backfill":
        _prompt_snapshot_backfill(args)


def _bootstrap_admin(args: argparse.Namespace) -> None:
    settings = get_settings()
    email = args.email or settings.admin_email
    display_name = args.display_name or settings.admin_display_name
    password = args.password or settings.admin_password
    if not password:
        raise SystemExit("Admin password is required via --password or AIMAGICIAN_ADMIN_PASSWORD")

    with SessionLocal() as db:
        user = bootstrap_admin(
            db,
            email=email,
            password=password,
            display_name=display_name,
            rotate_password=args.rotate_password,
        )
        db.commit()
        db.refresh(user)
        print(
            json.dumps(
                {
                    "admin_id": str(user.id),
                    "email": user.email,
                    "display_name": user.display_name,
                    "active": user.is_active,
                },
                ensure_ascii=False,
            )
        )


def _worker_claim(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        job = claim_next_job(db, worker_id=args.worker_id)
        db.commit()
        if job is None:
            print(json.dumps({"claimed": False}, ensure_ascii=False))
            return
        db.refresh(job)
        print(
            json.dumps(
                {
                    "claimed": True,
                    "job_id": str(job.id),
                    "run_id": str(job.run_id),
                    "job_type": job.job_type,
                    "status": job.status,
                    "worker_id": job.claimed_by,
                    "attempt_count": job.attempt_count,
                },
                ensure_ascii=False,
            )
        )


def _worker_run_once(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        if args.dry_run:
            print(json.dumps(describe_next_script_job(db), ensure_ascii=False))
            return
        try:
            job = execute_next_script_job(db, worker_id=args.worker_id, commit_started=True)
        except ScriptAdapterError as exc:
            db.commit()
            raise SystemExit(f"{exc.code}: {exc}") from exc
        db.commit()
        if job is None:
            print(json.dumps({"claimed": False, "executed": False}, ensure_ascii=False))
            return
        db.refresh(job)
        print(
            json.dumps(
                {
                    "claimed": True,
                    "executed": True,
                    "job_id": str(job.id),
                    "run_id": str(job.run_id),
                    "job_type": job.job_type,
                    "status": job.status,
                    "failure_code": job.failure_code,
                },
                ensure_ascii=False,
            )
        )


def _worker_loop(args: argparse.Namespace) -> None:
    result = run_worker_loop(
        session_factory=SessionLocal,
        worker_id=args.worker_id,
        poll_interval_seconds=args.poll_interval_seconds,
        max_jobs=args.max_jobs,
        max_idle_seconds=args.max_idle_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def _doctor(args: argparse.Namespace) -> None:
    result = run_deployment_doctor(create_artifact_root=not args.no_create_artifact_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_error and result["status"] == "error":
        raise SystemExit(1)


def _prompt_snapshot_backfill(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        result = backfill_prompt_snapshots(db, limit=args.limit or None)
        db.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
