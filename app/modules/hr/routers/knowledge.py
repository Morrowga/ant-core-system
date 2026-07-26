from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import (DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser,
                                   require_role, RequireActivePlan)
from app.core.services.base import TenantService

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))
Owner = Depends(require_role([ROLE_OWNER]))

knowledge_router = APIRouter(prefix="/knowledge/posts", tags=["knowledge"], dependencies=[RequireActivePlan])


@knowledge_router.get("")
async def list_posts(db: DB, user: CurrentUser, category: str | None = None, search: str | None = None,
                     post_type: str | None = None):
    from app.modules.hr.models.misc import KnowledgePost
    svc = TenantService(db, user)
    stmt = svc.tenant_select(KnowledgePost).where(KnowledgePost.deleted_at.is_(None))\
        .order_by(KnowledgePost.pinned.desc(),
                                                     KnowledgePost.created_at.desc())
    if post_type:
        stmt = stmt.where(KnowledgePost.post_type == post_type)
    if category:
        stmt = stmt.where(KnowledgePost.category == category)
    if search:
        stmt = stmt.where(KnowledgePost.title.ilike(f"%{search}%"))
    rows = (await db.execute(stmt)).scalars()
    return [{"id": p.id, "title": p.title, "category": p.category, "pinned": p.pinned,
             "must_acknowledge": p.must_acknowledge, "created_at": p.created_at,
             "post_type": p.post_type} for p in rows]


@knowledge_router.get("/{post_id}")
async def get_post(post_id: int, db: DB, user: CurrentUser):
    """`acknowledged_by_me` was missing entirely -- the mobile detail screen
    had no way to know a returning user already acknowledged this post, so
    it always showed the "I've read this" prompt again on every visit.

    New: also returns `comments` -- previously this endpoint never
    included them at all, which meant Sharing posts (whose entire point is
    open company-wide discussion) had no way to actually display any."""
    from app.modules.hr.models.misc import KnowledgeAcknowledgment, KnowledgeComment
    from app.core.models.user import User

    post = await _post_in_tenant(db, user, post_id)
    acked = (await db.execute(
        select(KnowledgeAcknowledgment).where(
            KnowledgeAcknowledgment.post_id == post_id,
            KnowledgeAcknowledgment.user_id == user.id,
        )
    )).scalar_one_or_none()

    comment_rows = (await db.execute(
        select(KnowledgeComment, User.full_name)
        .join(User, User.id == KnowledgeComment.author_id)
        .where(KnowledgeComment.post_id == post_id)
        .order_by(KnowledgeComment.created_at)
    )).all()

    return {"id": post.id, "author_id": post.author_id, "title": post.title, "body": post.body,
            "category": post.category, "pinned": post.pinned, "must_acknowledge": post.must_acknowledge,
            "acknowledged_by_me": acked is not None, "post_type": post.post_type,
            "comments": [
                {"id": c.id, "author_id": c.author_id, "comment": c.comment,
                 "author_name": author_name, "created_at": c.created_at}
                for c, author_name in comment_rows
            ]}


@knowledge_router.post("", status_code=201)
async def create_post(payload: dict, db: DB, user: CurrentUser):
    from app.modules.hr.models.misc import KnowledgePost

    post_type = payload.get("post_type", "knowledge")
    if post_type not in ("knowledge", "sharing"):
        post_type = "knowledge"

    # New: "sharing" posts are always open to anyone -- no company setting
    # gates them at all, unlike "knowledge" posts. Only knowledge checks
    # who_can_post.
    if post_type == "knowledge" and user.role == "employee":
        who_can_post = await _company_setting_value(db, user.company_id, "knowledge", "who_can_post",
                                                     default="admin_and_employee")
        if who_can_post == "admin_only":
            raise HTTPException(status_code=403, detail="Employee posting disabled by company settings")

    if post_type == "sharing":
        # Simple by design -- no category, no must-acknowledge, no deadline.
        # Enforced server-side too, not just left to the frontend disabling
        # those fields.
        category = None
        must_acknowledge = False
        ack_deadline_days = None
    else:
        category = payload.get("category")
        ack_deadline_days = payload.get("ack_deadline_days")
        must_acknowledge = bool(payload.get("must_acknowledge", False))
        # New: fall back to the company's configured default deadline when a
        # must-read post doesn't specify one explicitly -- previously always
        # fell through to None, ignoring default_ack_deadline_days entirely.
        if must_acknowledge and ack_deadline_days is None:
            ack_deadline_days = await _company_setting_value(db, user.company_id, "knowledge",
                                                              "default_ack_deadline_days", default=7)

    post = KnowledgePost(company_id=user.company_id, author_id=user.id,
                         title=payload.get("title", ""), body=payload.get("body", ""),
                         category=category,
                         must_acknowledge=must_acknowledge,
                         ack_deadline_days=ack_deadline_days,
                         post_type=post_type)
    db.add(post)
    await db.flush()
    return {"id": post.id}


@knowledge_router.post("/{post_id}/comment", status_code=201)
async def comment_post(post_id: int, payload: dict, db: DB, user: CurrentUser):
    from app.modules.hr.models.misc import KnowledgeComment
    await _post_in_tenant(db, user, post_id)
    c = KnowledgeComment(post_id=post_id, author_id=user.id, comment=payload.get("comment", ""))
    db.add(c)
    await db.flush()
    return {"id": c.id}


@knowledge_router.post("/{post_id}/acknowledge", status_code=201)
async def acknowledge_post(post_id: int, db: DB, user: CurrentUser):
    """Idempotent -- calling this twice (e.g. tapping "I've read this" AND
    posting a comment, which auto-acknowledges on mobile) must not insert a
    second row, or /acknowledgment-status's count would over-count this
    same user as multiple distinct acknowledgments."""
    from app.modules.hr.models.misc import KnowledgeAcknowledgment
    await _post_in_tenant(db, user, post_id)
    existing = (await db.execute(
        select(KnowledgeAcknowledgment).where(
            KnowledgeAcknowledgment.post_id == post_id,
            KnowledgeAcknowledgment.user_id == user.id,
        )
    )).scalar_one_or_none()
    if existing is None:
        db.add(KnowledgeAcknowledgment(post_id=post_id, user_id=user.id))
        await db.flush()
    return {"ok": True}


@knowledge_router.post("/{post_id}/pin")
async def pin_post(post_id: int, db: DB, user=DashUser):
    post = await _post_in_tenant(db, user, post_id)
    post.pinned = not post.pinned
    await db.flush()
    return {"pinned": post.pinned}


@knowledge_router.get("/{post_id}/acknowledgment-status")
async def ack_status(post_id: int, db: DB, user=DashUser):
    from sqlalchemy import func
    from app.modules.hr.models.misc import KnowledgeAcknowledgment
    from app.core.models.user import User
    await _post_in_tenant(db, user, post_id)
    total = await db.scalar(select(func.count(User.id)).where(
        User.company_id == user.company_id, User.active.is_(True)))
    acked = await db.scalar(select(func.count(KnowledgeAcknowledgment.id)).where(
        KnowledgeAcknowledgment.post_id == post_id))
    return {"acknowledged": acked or 0, "total_active_employees": total or 0}


@knowledge_router.patch("/{post_id}")
async def update_post(post_id: int, payload: dict, db: DB, user: CurrentUser):
    post = await _post_in_tenant(db, user, post_id)
    # Author can edit their own post; owners/managers can edit any.
    if user.role == "employee" and post.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not your post")
    for field in ("title", "body", "category", "must_acknowledge", "ack_deadline_days"):
        if field in payload:
            setattr(post, field, payload[field])
    await db.flush()
    return {"ok": True}


@knowledge_router.delete("/{post_id}", status_code=204)
async def delete_post(post_id: int, db: DB, user=DashUser):
    """Soft delete: hidden from all reads, row (and acknowledgments) preserved."""
    from datetime import datetime, timezone
    post = await _post_in_tenant(db, user, post_id)
    post.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return None


async def _post_in_tenant(db, user, post_id: int):
    from app.modules.hr.models.misc import KnowledgePost
    post = await db.get(KnowledgePost, post_id)
    if post is None or post.company_id != user.company_id or post.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


async def _company_setting_value(db, company_id: int, section: str, key: str, default):
    """Generalized from the old _company_setting_flag -- reads any value
    type (enum string, number, bool) from the company's settings JSON blob,
    not just booleans."""
    from app.core.models.company import CompanySettings
    row = (await db.execute(select(CompanySettings).where(
        CompanySettings.company_id == company_id, CompanySettings.section == section))).scalar_one_or_none()
    if row is None:
        return default
    return row.data_json.get(key, default)