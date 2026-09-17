"""
Google Calendar API wrapper
"""
import logging
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']


class GoogleCalendarClient:
    """Клиент для работы с Google Calendar API"""

    def __init__(self, credentials_file: str):
        """Инициализировать клиент Service Account"""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_file, scopes=SCOPES
            )
            self.service = build('calendar', 'v3', credentials=credentials, cache_discovery=False)
            logger.info("Google Calendar client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Google Calendar client: {e}")
            raise

    def get_events(self, calendar_id: str, days: int = 90) -> list[dict]:
        """
        Получить события с Google Calendar

        Args:
            calendar_id: ID календаря
            days: Количество дней в будущем для выборки

        Returns:
            Список событий
        """
        try:
            now = datetime.now(timezone.utc)
            future = now + timedelta(days=days)
            events = []
            page_token = None
            while True:
                result = self.service.events().list(
                    calendarId=calendar_id,
                    timeMin=now.isoformat(), timeMax=future.isoformat(),
                    singleEvents=True, orderBy='startTime', pageToken=page_token,
                ).execute()
                events.extend(result.get('items', []))
                page_token = result.get('nextPageToken')
                if not page_token:
                    break
            # A cancellation pass is allowed only after every page succeeded.
            self.sync_window = (now, future)
            logger.info(f"Fetched {len(events)} events from Google Calendar")
            return events
        except Exception as e:
            logger.error(f"Failed to fetch events from Google Calendar: {e}")
            raise

    def create_event(self, calendar_id: str, event_data: dict) -> dict:
        """
        Создать событие в Google Calendar

        Args:
            calendar_id: ID календаря
            event_data: Данные события (summary, start, end, location, description)

        Returns:
            Созданное событие
        """
        try:
            event = self.service.events().insert(
                calendarId=calendar_id,
                body=event_data
            ).execute()
            logger.info(f"Created event in Google Calendar: {event['id']}")
            return event
        except Exception as e:
            logger.error(f"Failed to create event in Google Calendar: {e}")
            raise

    def ensure_planned_event(self, calendar_id: str, event_id: str, event_data: dict) -> dict:
        """An explicit Google id makes retries after an unknown response safe."""
        from googleapiclient.errors import HttpError
        events = self.service.events()
        try:
            result = events.get(calendarId=calendar_id, eventId=event_id).execute()
        except HttpError as exc:
            if exc.resp.status != 404:
                raise
            try:
                result = events.insert(calendarId=calendar_id, body={**event_data, 'id': event_id}).execute()
            except HttpError as conflict:
                if conflict.resp.status != 409:
                    raise
                result = events.get(calendarId=calendar_id, eventId=event_id).execute()
        if result.get('status') == 'cancelled':
            raise ValueError('Созданное событие уже удалено из Google Calendar. Проверьте расписание.')
        for field in ('summary', 'location', 'description'):
            if (result.get(field) or '') != (event_data.get(field) or ''):
                raise ValueError('Событие изменено в Google Calendar. Проверьте расписание перед повторной записью.')
        for field in ('start', 'end'):
            if datetime.fromisoformat(result[field]['dateTime']) != datetime.fromisoformat(event_data[field]['dateTime']):
                raise ValueError('Время события изменено в Google Calendar. Проверьте расписание.')
        return result

    def update_event(self, calendar_id: str, event_id: str, event_data: dict) -> dict:
        """
        Обновить событие в Google Calendar

        Args:
            calendar_id: ID календаря
            event_id: ID события
            event_data: Новые данные события

        Returns:
            Обновленное событие
        """
        try:
            event = self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event_data
            ).execute()
            logger.info(f"Updated event in Google Calendar: {event_id}")
            return event
        except Exception as e:
            logger.error(f"Failed to update event in Google Calendar: {e}")
            raise

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        """
        Удалить событие из Google Calendar

        Args:
            calendar_id: ID календаря
            event_id: ID события
        """
        try:
            self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            logger.info(f"Deleted event from Google Calendar: {event_id}")
        except Exception as e:
            logger.error(f"Failed to delete event from Google Calendar: {e}")
            raise
