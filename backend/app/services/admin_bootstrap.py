from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.security.passwords import hash_password
from app.services.audit import record_audit_event


def normalize_email(email: str) -> str:
    return email.strip().lower()


def bootstrap_admin(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    rotate_password: bool = False,
) -> User:
    normalized_email = normalize_email(email)
    user = db.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=normalized_email,
            display_name=display_name.strip() or normalized_email,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(user)
        db.flush()
        record_audit_event(
            db,
            event_type="admin.bootstrap.created",
            actor_type="system",
            actor_user_id=user.id,
            message="Admin user bootstrapped",
            payload={"email": normalized_email},
        )
        return user

    if rotate_password:
        user.password_hash = hash_password(password)
        user.display_name = display_name.strip() or user.display_name
        user.failed_login_count = 0
        record_audit_event(
            db,
            event_type="admin.bootstrap.password_rotated",
            actor_type="system",
            actor_user_id=user.id,
            message="Admin password rotated",
            payload={"email": normalized_email},
        )
    else:
        record_audit_event(
            db,
            event_type="admin.bootstrap.skipped",
            actor_type="system",
            actor_user_id=user.id,
            message="Admin already exists; password not rotated",
            payload={"email": normalized_email},
        )
    return user
