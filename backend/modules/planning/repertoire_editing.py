"""Read daily cast answers and review a locally edited repertoire draft."""
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from core.database import get_db
from core.time import local_now
from .repertoire import Pin, RepertoireProblem
from .repertoire_source import get_rules
from .repertoire_search import draft_variant
from .services import match_roles, norm

router = APIRouter()


def daily_problem(source, rules):
    # Monthly quantities are goals for a manual draft, not a reason to hide
    # a show or its answers. All other date/cast/time constraints still apply.
    probe = rules.model_copy(deep=True)
    fixed = Counter(e['key'] for e in source['fixed'] if e['date'].startswith(source['month']))
    for rule in probe.shows:
        rule.count = fixed[rule.key] + 1
    probe.pins = []
    return RepertoireProblem(source, probe, local_now().date())


@router.get('/repertoire/day')
def day_choices(month: str, day: date, db: Session = Depends(get_db)):
    from .repertoire_router import valid_month, snapshot
    valid_month(month)
    if day.strftime('%Y-%m') != month:
        raise HTTPException(422, 'Дата должна принадлежать выбранному месяцу')
    source = snapshot(db, month)
    rules, revision, _ = get_rules(db, month, source['shows'])
    problem = daily_problem(source, rules)
    shows = []
    pin = next((p for p in rules.pins if p.day == day), None)
    for diagnostic in problem.diagnostics:
        cell = next((d for d in diagnostic['dates'] if d['date'] == day.isoformat()), None)
        if cell is None:
            continue
        actors = {norm(a['name']): a for r in cell['roles'] for a in r['actors']}
        votes = Counter(a['status'] for a in actors.values())
        reason = cell['reason']
        if pin and pin.key != diagnostic['key']:
            reason = 'На эту дату закреплён другой спектакль. Сначала снимите закрепление.'
        shows.append({**cell, 'key': diagnostic['key'], 'name': diagnostic['name'], 'reason': reason,
                      'covered': len(match_roles(cell['roles'])), 'total': len(cell['roles']),
                      'votes': {'yes': votes['yes'] + votes['assigned'], 'no': votes['no'],
                                'other': len(actors) - votes['yes'] - votes['assigned'] - votes['no']}})
    return {'month': month, 'day': day.isoformat(), 'fingerprint': source['fingerprint'],
            'revision': revision, 'shows': shows}


class DraftRequest(BaseModel):
    month: str
    entries: list[Pin] = Field(max_length=31)
    expected_fingerprint: str
    expected_revision: int = Field(ge=0)

    @model_validator(mode='after')
    def unique_dates(self):
        if len({e.day for e in self.entries}) != len(self.entries):
            raise ValueError('На дату можно поставить только один спектакль')
        return self


@router.post('/repertoire/draft')
def review_draft(req: DraftRequest, db: Session = Depends(get_db)):
    from .repertoire_router import valid_month, snapshot
    valid_month(req.month)
    source = snapshot(db, req.month)
    rules, revision, _ = get_rules(db, req.month, source['shows'])
    if source['fingerprint'] != req.expected_fingerprint or revision != req.expected_revision:
        raise HTTPException(409, 'Ответы, календарь или параметры изменились. Обновите план и повторите замену.')
    from .repertoire_publication import assert_no_publication
    assert_no_publication(db, req.month)
    from .models import RepertoireAffiche
    if db.get(RepertoireAffiche, req.month):
        raise HTTPException(409, 'Афиша месяца закреплена. Сначала снимите закрепление.')
    return {**review_entries(source, rules, req.entries), 'fingerprint': source['fingerprint'], 'revision': revision}


def review_entries(source, rules, entries):
    month = source['month']
    probe = daily_problem(source, rules)
    pairs = {(e.day.isoformat(), e.key) for e in entries}
    fixed = {(e['date'], e['key']) for e in source['fixed'] if e['date'].startswith(month)}
    if any((p.day.isoformat(), p.key) not in pairs | fixed for p in rules.pins):
        raise HTTPException(409, 'Замена меняет закреплённые даты. Сначала снимите соответствующее закрепление.')
    selected = []
    for entry in sorted(entries, key=lambda e: e.day):
        day = entry.day.isoformat()
        if entry.day.strftime('%Y-%m') != month:
            raise HTTPException(422, 'Все даты должны принадлежать выбранному месяцу')
        if (day, entry.key) in fixed:
            # A draft show may have been assigned since the previous review.
            # Keep it once as a fixed event instead of losing the rest of the draft.
            continue
        cell = probe.options.get(day, {}).get(entry.key)
        if cell is None:
            reason = next((d['reason'] for show in probe.diagnostics if show['key'] == entry.key
                           for d in show['dates'] if d['date'] == day), None)
            raise HTTPException(409, f'{day}: {reason or "спектакль недоступен"}')
        selected.append((day, entry.key, cell))
    problem = RepertoireProblem(source, rules, local_now().date())
    result = draft_variant(problem, selected)
    if result['status'] == 'invalid':
        raise HTTPException(409, 'С этими датами не собирается состав без запрещённой нагрузки. Выберите другой спектакль или измените правило нагрузки.')
    return result
