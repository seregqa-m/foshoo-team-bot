from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from core.database import SessionLocal
from .models import AppUser, SuperAdmin, AdminSetup, AdminAudit

BOOTSTRAP_KEY = 'superadmins_v1'


def bootstrap_superadmin(db, initial_id):
    """Import ADMIN_ID once; a restart must never undo an explicit revocation."""
    if db.get(AdminSetup, BOOTSTRAP_KEY) or not initial_id:
        return False
    if not db.get(AppUser, initial_id):
        db.add(AppUser(telegram_user_id=initial_id, username='', display_name='', search_text=str(initial_id)))
    if not db.get(SuperAdmin, initial_id):
        db.add(SuperAdmin(telegram_user_id=initial_id, granted_by=initial_id))
        db.add(AdminAudit(actor_id=initial_id, target_id=initial_id, action='bootstrap'))
    db.add(AdminSetup(key=BOOTSTRAP_KEY))
    db.commit()
    return True


def has_superadmin_role(user_id):
    with SessionLocal() as db:
        return db.get(SuperAdmin, user_id) is not None


def remember_identity(user):
    """Register only a verified Telegram identity, even if entry was denied."""
    with SessionLocal() as db:
        row = db.get(AppUser, user.id)
        search_text = f'{user.display_name} {user.username} {user.id}'.casefold()
        if row and row.username == user.username and row.display_name == user.display_name and row.search_text == search_text:
            return
        if not row:
            row = AppUser(telegram_user_id=user.id)
            db.add(row)
        row.username, row.display_name = user.username, user.display_name
        row.search_text = search_text
        row.updated_at = datetime.utcnow()
        try:
            db.commit()
        except IntegrityError:
            # Two tabs may register the same Telegram user simultaneously.
            db.rollback()
            row = db.get(AppUser, user.id)
            if row is None:
                raise
            row.username, row.display_name, row.search_text = user.username, user.display_name, search_text
            row.updated_at = datetime.utcnow()
            db.commit()


def change_role(db, actor_id, target_id, grant):
    try:
        # Updating one persistent row serializes concurrent changes in the DB.
        # Recheck the caller only after acquiring the lock (including self-revocation).
        changed = db.execute(update(AdminSetup).where(AdminSetup.key == BOOTSTRAP_KEY)
                             .values(revision=AdminSetup.revision + 1)).rowcount
        if not changed:
            raise HTTPException(503, 'Первый суперадминистратор ещё не настроен')
        if not db.get(SuperAdmin, actor_id, populate_existing=True):
            raise HTTPException(403, 'Управление доступно только суперадминистратору')
        existing = db.get(SuperAdmin, target_id, populate_existing=True)
        if grant:
            if not db.get(AppUser, target_id):
                raise HTTPException(404, 'Сначала попросите человека открыть мини-приложение через Telegram')
            if not existing:
                db.add(SuperAdmin(telegram_user_id=target_id, granted_by=actor_id))
                db.add(AdminAudit(actor_id=actor_id, target_id=target_id, action='grant'))
        elif existing:
            if db.query(SuperAdmin).count() <= 1:
                raise HTTPException(409, 'Нельзя удалить последнего суперадминистратора')
            db.delete(existing)
            db.add(AdminAudit(actor_id=actor_id, target_id=target_id, action='revoke'))
        db.commit()
    except Exception:
        db.rollback()
        raise
