import logging
import re
from datetime import date, datetime, time
from threading import RLock

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.time import local_now
from config import TIMEZONE
from modules.attendance.services import answer_lock
from .models import RepertoireSettings
from .repertoire import Rules, RepertoireProblem, load_warnings
from .repertoire_source import load_snapshot, get_rules
from .repertoire_search import search_page

logger = logging.getLogger(__name__)
settings_lock = RLock()
router = APIRouter()


def valid_month(month):
    try:
        if not re.fullmatch(r'\d{4}-\d{2}', month):
            raise ValueError()
        first = date.fromisoformat(month + '-01')
        if not 1901 <= first.year <= 9998:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, 'Месяц должен быть в формате ГГГГ-ММ (1901–9998)')
    return month


def snapshot(db, month, fresh=False):
    from .router import get_client
    try:
        return load_snapshot(db, get_client(), month, fresh)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('Cannot read repertoire sources')
        raise HTTPException(502, 'Не удалось обновить график, составы или календарь. Предыдущие предложения могли устареть.') from exc


@router.get('/repertoire')
def get_repertoire(month: str, page: int = Query(0, ge=0), selected: str | None = None, db: Session = Depends(get_db)):
    valid_month(month)
    data = snapshot(db, month)
    rules, revision, defaults_revision = get_rules(db, month, data['shows'])
    problem = RepertoireProblem(data, rules, local_now().date())
    return {**search_page(problem, page, selected), 'month': month, 'rules': rules.model_dump(mode='json'),
            'revision': revision, 'defaults_revision': defaults_revision, 'shows': data['shows'],
            'fingerprint': data['fingerprint'], 'diagnostics': problem.diagnostics, 'warnings': data['warnings'],
            'checked_at': local_now().isoformat(), 'timezone': TIMEZONE}


class SaveRules(BaseModel):
    month: str
    rules: Rules
    expected_revision: int = Field(ge=0)
    expected_defaults_revision: int = Field(ge=0)
    use_as_default: bool = False


@router.put('/repertoire')
def save_repertoire(req: SaveRules, db: Session = Depends(get_db)):
    valid_month(req.month)
    if any(p.day.strftime('%Y-%m') != req.month for p in req.rules.pins):
        raise HTTPException(422, 'Закреплённая дата должна принадлежать выбранному месяцу')
    keys = {s.key for s in req.rules.shows}
    if any(p.key not in keys for p in req.rules.pins):
        raise HTTPException(422, 'Спектакль закрепления отсутствует в параметрах')
    with settings_lock:
        db.expire_all()
        row = db.get(RepertoireSettings, req.month)
        default = db.get(RepertoireSettings, '*')
        if (row.revision if row else 0) != req.expected_revision or (
            (req.use_as_default or not row) and (default.revision if default else 0) != req.expected_defaults_revision
        ):
            raise HTTPException(409, 'Параметры изменены другим администратором. Обновите блок и проверьте изменения.')
        if row is None:
            row = RepertoireSettings(month=req.month, revision=0)
            db.add(row)
        row.payload = req.rules.model_dump_json()
        row.revision += 1
        if req.use_as_default:
            if default is None:
                default = RepertoireSettings(month='*', revision=0)
                db.add(default)
            base = req.rules.model_copy(deep=True)
            base.pins = []
            default.payload = base.model_dump_json()
            default.revision += 1
        db.commit()
        return {'revision': row.revision}


class PrepareAssignment(BaseModel):
    month: str
    day: date
    key: str
    expected_fingerprint: str
    expected_revision: int = Field(ge=0)


def validate_review(db, client, req, day):
    """Recheck the recommendation immediately before an actual calendar write."""
    data = load_snapshot(db, client, req.month, fresh=True)
    rules, revision, _ = get_rules(db, req.month, data['shows'])
    review = req.repertoire
    if data['fingerprint'] != review.fingerprint or revision != review.revision:
        raise HTTPException(409, 'Календарь, ответы или параметры афиши изменились. Обновите предложения перед назначением.')
    problem = RepertoireProblem(data, rules, local_now().date())
    choices = {(d, k) for d, cells in problem.options.items() for k in cells}
    choices.update((d, k) for d, k, _ in problem.pinned)
    if (day.isoformat(), review.key) not in choices or problem.names.get(review.key) != req.show_name or problem.pin_errors:
        raise HTTPException(409, 'Дата или спектакль больше не подходят для этого плана')
    if rules.load_mode == 'forbid':
        baseline = load_warnings(data['fixed'], rules.streak)
        updated = load_warnings(data['fixed'] + [{'date': day.isoformat(), 'cast': req.cast}], rules.streak)
        if any(w not in baseline for w in updated):
            raise HTTPException(409, 'Выбранный состав нарушает запрет игровых дней подряд. Выберите других исполнителей.')


@router.post('/repertoire/prepare')
def prepare_assignment(req: PrepareAssignment, db: Session = Depends(get_db)):
    """Explicitly prepare an empty Sheets date, then use the existing audited assignment."""
    from .router import get_client, get_planning
    valid_month(req.month)
    if req.day.strftime('%Y-%m') != req.month or req.day < local_now().date():
        raise HTTPException(422, 'Выберите будущую дату в выбранном месяце')
    with settings_lock, answer_lock:
        data = snapshot(db, req.month, fresh=True)
        rules, revision, _ = get_rules(db, req.month, data['shows'])
        if revision != req.expected_revision or data['fingerprint'] != req.expected_fingerprint:
            raise HTTPException(409, 'Ответы, календарь или параметры изменились. Обновите предложения.')
        problem = RepertoireProblem(data, rules, local_now().date())
        options = {(day, key) for day, cells in problem.options.items() for key in cells}
        options.update((day, key) for day, key, _ in problem.pinned)
        if (req.day.isoformat(), req.key) not in options or problem.pin_errors:
            raise HTTPException(409, 'Дата больше не подходит для назначения')
        client = get_client()
        client.ensure_schedule_columns([(datetime.combine(req.day, time()), '')])
        # Force the projection cache to observe the newly created column.
        refreshed = load_snapshot(db, client, req.month, fresh=True)
        plan = get_planning(req.month, db)
        slot = next((s for s in plan['slots'] if s['date'] == req.day.isoformat()), None)
        name = next(s['name'] for s in data['shows'] if s['key'] == req.key)
        return {'plan': plan, 'column': slot['column'], 'show': name,
                'repertoire': {'key': req.key, 'fingerprint': refreshed['fingerprint'], 'revision': revision}}
