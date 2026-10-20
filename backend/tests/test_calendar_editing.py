import copy
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

with patch.dict(os.environ, {"BOT_TOKEN": "123456:offline-test-token", "DATABASE_URL": "sqlite://"},
                clear=True), patch("dotenv.load_dotenv"):
    from core.database import Base
    from core.time import as_local
    from modules.calendar.models import CalendarEvent
    from modules.calendar.services import CalendarService
    from modules.calendar.editing import editor_data
    from modules.calendar.google_client import GoogleCalendarClient
    from modules.polling.models import Poll
from fastapi import HTTPException
from googleapiclient.errors import HttpError
from httplib2 import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class CalendarEditingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.row = CalendarEvent(google_event_id="occurrence", title="Старое",
                                 start_time=datetime(2026, 10, 20, 19), end_time=datetime(2026, 10, 20, 21))
        self.db.add(self.row)
        self.db.commit()
        self.parent = dict(
            id="parent", etag='"parent-v1"', summary="Вся серия", description="Описание",
            location="Зал", recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TU"],
            start={"dateTime": "2024-01-02T19:00:00+03:00", "timeZone": "Europe/Moscow"},
            end={"dateTime": "2024-01-02T21:00:00+03:00", "timeZone": "Europe/Moscow"},
            attendees=[{"email": "example@example.org"}], reminders={"useDefault": True},
        )
        self.instance = {
            **copy.deepcopy(self.parent), "id": "occurrence", "etag": '"instance-v1"',
            "summary": "Этот повтор", "recurringEventId": "parent",
            "start": {"dateTime": "2026-10-20T19:00:00+03:00"},
            "end": {"dateTime": "2026-10-20T21:00:00+03:00"},
        }
        del self.instance["recurrence"]
        self.client = MagicMock()
        self.client.get_event.side_effect = lambda calendar, ident: copy.deepcopy(
            self.parent if ident == "parent" else self.instance)
        self.client.patch_event.side_effect = lambda calendar, ident, data, etag: {
            **copy.deepcopy(self.parent if ident == "parent" else self.instance), **data}
        self.service = CalendarService(self.db, self.client)

    def test_editor_distinguishes_occurrence_from_parent_without_creating_rows(self):
        single = editor_data(self.service, "calendar", self.row.id)
        series = editor_data(self.service, "calendar", self.row.id, "series")
        self.assertTrue(single["is_recurring"])
        self.assertEqual(single["title"], "Этот повтор")
        self.assertEqual(series["title"], "Вся серия")
        self.assertEqual(series["start_time"], self.parent["start"]["dateTime"])
        self.assertEqual(series["etag"], '"parent-v1"')
        self.assertEqual(self.db.query(CalendarEvent).count(), 1)

    def test_single_edit_patches_only_occurrence_and_preserves_metadata_and_frozen_poll_date(self):
        original_day = self.row.start_time.date()
        poll = Poll(calendar_event_id=self.row.id, selected_date=original_day)
        self.db.add(poll)
        self.db.commit()
        result = self.service.update_event(
            "calendar", self.row.id, title="Новое", location="", expected_etag='"instance-v1"',
            start_time=datetime(2026, 10, 21, 20), end_time=datetime(2026, 10, 21, 22))
        args = self.client.patch_event.call_args.args
        self.assertEqual(args[1], "occurrence")
        self.assertNotIn("recurrence", args[2])
        self.assertNotIn("attendees", args[2])
        self.assertNotIn("reminders", args[2])
        self.assertEqual(args[2]["location"], "")
        self.assertTrue(result["synced"])
        self.assertEqual(self.row.start_time.date().isoformat(), "2026-10-21")
        self.assertEqual(self.row.description, "Описание")
        self.assertEqual(poll.selected_date, original_day)

    def test_series_edit_patches_parent_once_then_refreshes_history(self):
        past = CalendarEvent(google_event_id="old", title="Старое",
                             start_time=datetime(2024, 1, 2, 19), end_time=datetime(2024, 1, 2, 21))
        self.db.add(past)
        self.db.commit()
        changed = {**self.instance, "summary": "Общее название"}
        self.client.get_events.return_value = [
            changed, {**self.parent, "id": "old", "summary": "Общее название"}]
        self.client.sync_window = (as_local(datetime(2024, 1, 1)), as_local(datetime(2027, 1, 1)))
        with patch("modules.calendar.editing.local_now", return_value=as_local(datetime(2026, 10, 20))):
            result = self.service.update_event("calendar", self.row.id, scope="series",
                                              expected_etag='"parent-v1"', title="Общее название")
        self.client.patch_event.assert_called_once_with(
            "calendar", "parent", {"summary": "Общее название"}, '"parent-v1"')
        self.assertGreater(self.client.get_events.call_args.kwargs["past_days"], 365)
        self.assertEqual(past.title, "Общее название")
        self.assertEqual(self.row.title, "Общее название")
        self.assertTrue(result["synced"])
        self.assertEqual(self.db.query(CalendarEvent).count(), 2)
        self.client.create_event.assert_not_called()

    def test_changed_google_etag_rejects_form_without_writing(self):
        with self.assertRaises(HTTPException) as error:
            self.service.update_event("calendar", self.row.id, scope="series",
                                      expected_etag='"old"', title="Новое")
        self.assertEqual(error.exception.status_code, 409)
        self.client.patch_event.assert_not_called()
        self.assertEqual(self.row.title, "Старое")

    def test_race_during_google_write_is_conflict_and_keeps_cache(self):
        self.client.patch_event.side_effect = HttpError(Response({"status": 412}), b'{}')
        with self.assertRaises(HTTPException) as error:
            self.service.update_event("calendar", self.row.id, expected_etag='"instance-v1"', title="Новое")
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.row.title, "Старое")

    def test_no_series_option_for_standalone_and_no_guessing_id_prefixes(self):
        self.instance.pop("recurringEventId")
        self.assertFalse(editor_data(self.service, "calendar", self.row.id)["is_recurring"])
        with self.assertRaises(HTTPException) as error:
            self.service.update_event("calendar", self.row.id, scope="series", expected_etag='"instance-v1"')
        self.assertEqual(error.exception.status_code, 400)
        self.client.patch_event.assert_not_called()

    def test_series_requires_reviewed_version(self):
        with self.assertRaises(HTTPException) as error:
            self.service.update_event("calendar", self.row.id, scope="series", title="Новое")
        self.assertEqual(error.exception.status_code, 409)
        self.client.patch_event.assert_not_called()

    def test_all_day_edit_preserves_date_fields(self):
        self.instance["start"] = {"date": "2026-10-20"}
        self.instance["end"] = {"date": "2026-10-21"}
        self.assertTrue(editor_data(self.service, "calendar", self.row.id)["all_day"])
        self.service.update_event("calendar", self.row.id, start_time=datetime(2026, 10, 22),
                                  end_time=datetime(2026, 10, 24))
        data = self.client.patch_event.call_args.args[2]
        self.assertEqual(data, {"start": {"date": "2026-10-22"}, "end": {"date": "2026-10-24"}})

    def test_invalid_interval_cannot_change_google(self):
        with self.assertRaises(ValueError):
            self.service.update_event("calendar", self.row.id, start_time=datetime(2026, 10, 22))
        self.client.patch_event.assert_not_called()

    def test_google_save_survives_failed_cache_refresh_with_explicit_warning(self):
        self.client.get_events.side_effect = TimeoutError()
        with self.assertLogs("modules.calendar.editing", level="ERROR"):
            result = self.service.update_event("calendar", self.row.id, scope="series",
                                              expected_etag='"parent-v1"', title="Новое")
        self.assertFalse(result["synced"])
        self.assertIn("сохранена в Google", result["warning"])
        self.client.patch_event.assert_called_once()
        self.assertEqual(self.row.title, "Старое")

    def test_google_client_uses_conditional_patch_without_sending_notifications(self):
        client = GoogleCalendarClient.__new__(GoogleCalendarClient)
        client.service = MagicMock()
        request = client.service.events.return_value.patch.return_value
        request.headers = {}
        client.patch_event("calendar", "parent", {"summary": "Новое"}, '"v1"')
        client.service.events.return_value.patch.assert_called_once_with(
            calendarId="calendar", eventId="parent", body={"summary": "Новое"}, sendUpdates="none")
        self.assertEqual(request.headers["If-Match"], '"v1"')
        client.service.events.return_value.insert.assert_not_called()
