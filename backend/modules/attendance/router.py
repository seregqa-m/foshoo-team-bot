"""Personal day answers, independent of the original Telegram publication."""
import re
from calendar import monthrange
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.time import local_now
from .models import DayAnswer
from .services import answer_lock, record_answers

router = APIRouter(prefix='/api/attendance', tags=['attendance'])


def _day_data(row, today):
    return {
        'date': row.day.isoformat(),
        'answer': None if row.answer == 'retracted' else (
            'unknown' if row.answer == 'maybe' else row.answer),
        'revision': row.revision,
        'editable': row.day >= today,
    }


@router.get('/me')
def my_answers(request: Request, month: str | None = None, db: Session = Depends(get_db)):
    today = local_now().date()
    user = request.state.telegram_user
    if month is None:
        upcoming = db.query(DayAnswer).filter(
            DayAnswer.user_id == user.id, DayAnswer.day >= today,
        ).order_by(DayAnswer.day).first()
        month = (upcoming.day if upcoming else today).strftime('%Y-%m')
    try:
        if not re.fullmatch(r'\d{4}-\d{2}', month):
            raise ValueError
        first = date.fromisoformat(month + '-01')
    except ValueError as exc:
        raise HTTPException(422, 'Месяц должен быть в формате ГГГГ-ММ') from exc
    last = first.replace(day=monthrange(first.year, first.month)[1])
    rows = db.query(DayAnswer).filter(
        DayAnswer.user_id == user.id, DayAnswer.day >= first, DayAnswer.day <= last,
    ).order_by(DayAnswer.day).all()
    return {'month': month, 'days': [_day_data(row, today) for row in rows]}


class PersonalAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date: date
    answer: Literal['yes', 'no', 'unknown']
    expected_revision: int = Field(ge=1)


@router.put('/me')
def change_answer(payload: PersonalAnswer, request: Request, db: Session = Depends(get_db)):
    user = request.state.telegram_user
    today = local_now().date()
    if payload.date < today:
        raise HTTPException(422, 'Ответы за прошедшие дни изменить нельзя')
    with answer_lock:
        # Re-read under the same lock as polling and cast assignments.
        db.expire_all()
        row = db.get(DayAnswer, (user.id, payload.date))
        if row is None:
            raise HTTPException(404, 'На эту дату ещё нет вашего ответа в опросах бота')
        source = f'app:{payload.date.isoformat()}:{payload.expected_revision}'
        # A retry after a lost response is safe only while this exact write is current.
        if (row.revision == payload.expected_revision + 1
                and row.source == source and row.answer == payload.answer):
            return _day_data(row, today)
        if row.revision != payload.expected_revision:
            raise HTTPException(409, 'Ответ уже изменился. Проверьте актуальное значение и повторите выбор.')
        if row.answer != payload.answer:
            record_answers(db, user.id, user.username, source, {payload.date: payload.answer})
            db.commit()
        # The minute worker exports committed revisions; Sheets outages cannot
        # turn a successful personal answer into a failed or repeated request.
        return _day_data(row, today)
