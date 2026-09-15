"""Calendar wall time is stored in the configured zone for legacy compatibility.

SQLite drops offsets. Normalize before storage and attach the zone on reads so
API clients always receive an unambiguous ISO timestamp. Audit timestamps and
poll expiration continue to use UTC.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator
from config import TIMEZONE

LOCAL_TZ = ZoneInfo(TIMEZONE)


def local_now():
    return datetime.now(LOCAL_TZ)


def as_local(value):
    return value.replace(tzinfo=LOCAL_TZ) if value.tzinfo is None else value.astimezone(LOCAL_TZ)


class CalendarDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return as_local(value).replace(tzinfo=None) if value is not None else None

    def process_result_value(self, value, dialect):
        return as_local(value) if value is not None else None
