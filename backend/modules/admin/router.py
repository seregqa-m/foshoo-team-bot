from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from core.database import get_db
from .models import AppUser, SuperAdmin, AdminAudit
from .services import change_role


def require_superadmin(request: Request, db: Session = Depends(get_db)):
    # A fresh DB check also protects reads from a recently revoked global role.
    user = request.state.telegram_user
    if not db.get(SuperAdmin, user.id):
        raise HTTPException(403, 'Управление доступно только суперадминистратору')
    return user


router = APIRouter(prefix='/api/admin', tags=['admin'], dependencies=[Depends(require_superadmin)])


def identity(row, user_id):
    return {'telegram_user_id': user_id, 'username': row.username if row else '',
            'display_name': row.display_name if row else ''}


@router.get('/superadmins')
def list_superadmins(db: Session = Depends(get_db)):
    admins = []
    for role in db.query(SuperAdmin).order_by(SuperAdmin.granted_at, SuperAdmin.telegram_user_id).all():
        admins.append({**identity(db.get(AppUser, role.telegram_user_id), role.telegram_user_id),
                       'granted_at': role.granted_at.isoformat(), 'granted_by': role.granted_by})
    audit = [{**identity(db.get(AppUser, a.target_id), a.target_id), 'id': a.id,
              'actor_id': a.actor_id, 'action': a.action, 'created_at': a.created_at.isoformat() + 'Z'}
             for a in db.query(AdminAudit).order_by(AdminAudit.id.desc()).limit(30).all()]
    return {'admins': admins, 'audit': audit}


@router.get('/users')
def search_users(q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db)):
    q = q.strip().lstrip('@')
    if len(q) < 2:
        return {'users': []}
    search = q.casefold().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    # Persisted casefolded text also supports Russian names in SQLite.
    conditions = [AppUser.search_text.like(f'%{search}%', escape='\\')]
    if q.isascii() and q.isdigit() and int(q) <= 2**63 - 1:
        conditions.append(AppUser.telegram_user_id == int(q))
    rows = db.query(AppUser).filter(or_(*conditions)).order_by(AppUser.username, AppUser.telegram_user_id).limit(20).all()
    role_ids = {r.telegram_user_id for r in db.query(SuperAdmin).all()}
    return {'users': [{**identity(row, row.telegram_user_id), 'is_superadmin': row.telegram_user_id in role_ids} for row in rows]}


class GrantRequest(BaseModel):
    telegram_user_id: int = Field(strict=True, gt=0, le=2**63 - 1)


@router.post('/superadmins')
def grant_superadmin(req: GrantRequest, request: Request, db: Session = Depends(get_db)):
    change_role(db, request.state.telegram_user.id, req.telegram_user_id, True)
    return {'status': 'granted'}


@router.delete('/superadmins/{target_id}')
def revoke_superadmin(target_id: int, request: Request, db: Session = Depends(get_db)):
    change_role(db, request.state.telegram_user.id, target_id, False)
    return {'status': 'revoked'}
