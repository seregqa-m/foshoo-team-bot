"""Read the saved monthly affiche and explicitly unlock it without calendar rollback."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.time import local_now
from .models import RepertoireAffiche, RepertoireSettings
from .repertoire import Pin, RepertoireProblem
from .repertoire_source import get_rules
from .repertoire_search import search_key
from .repertoire_editing import review_entries

router = APIRouter()


def pair_set(entries):
    return {(e['date'], e['key']) for e in entries}


def check_locked_day(db, month, day, key):
    row = db.get(RepertoireAffiche, month)
    if row and (day.isoformat(), key) not in pair_set(json.loads(row.payload)['entries']):
        raise HTTPException(409, 'Этот показ не входит в закреплённую афишу. Сначала снимите закрепление.')


def locked_result(row, source, rules):
    saved = json.loads(row.payload)
    variant, error, pending = saved, None, False
    try:
        fixed = pair_set([e for e in source['fixed'] if e['date'].startswith(source['month'])])
        if not pair_set([e for e in saved['entries'] if e['fixed']]) <= fixed or not fixed <= pair_set(saved['entries']):
            raise HTTPException(409, 'Назначенные показы в календаре изменились. Снимите закрепление и проверьте афишу.')
        reviewed = review_entries(source, rules, [Pin(day=e['date'], key=e['key']) for e in saved['entries']])
        pending = reviewed['status'] == 'calculating'
        if not pending:
            variant = reviewed['variant']
    except HTTPException as exc:
        error = str(exc.detail)
    problem = RepertoireProblem(source, rules, local_now().date())
    return {'locked': True, 'lock_error': error, 'lock_pending': pending,
            'variants': [variant], 'selected_variant': variant, 'recommended_id': None,
            'search_id': search_key(problem), 'total_variants': 1, 'considered_variants': 1,
            'page': 0, 'page_size': 5, 'complete': not pending, 'maximum': variant['count'],
            'upper_bound': problem.upper, 'target': problem.target, 'search_steps': 0, 'pin_errors': []}


class LockRequest(BaseModel):
    month: str
    search_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    variant_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_fingerprint: str
    expected_revision: int = Field(ge=0)


class UnlockRequest(BaseModel):
    month: str
    expected_revision: int = Field(ge=0)


def save_revision(db, month, rules, revision):
    row = db.get(RepertoireSettings, month)
    if row is None:
        row = RepertoireSettings(month=month)
        db.add(row)
    row.payload, row.revision = rules.model_dump_json(), revision + 1
    return revision + 1


@router.post('/repertoire/unlock')
def unlock_affiche(req: UnlockRequest, request: Request, db: Session = Depends(get_db)):
    from .repertoire_router import valid_month, settings_lock
    from .repertoire_publication import require_superadmin, assert_no_publication
    require_superadmin(request)
    valid_month(req.month)
    with settings_lock:
        assert_no_publication(db, req.month)
        db.expire_all()
        rules, revision, _ = get_rules(db, req.month, [])
        if revision != req.expected_revision:
            raise HTTPException(409, 'Афиша изменена другим администратором. Обновите план.')
        row = db.get(RepertoireAffiche, req.month)
        if row:
            db.delete(row)
        # Legacy per-show pins are released together from the single month control.
        rules.pins = []
        revision = save_revision(db, req.month, rules, revision)
        db.commit()
        return {'locked': False, 'revision': revision}
