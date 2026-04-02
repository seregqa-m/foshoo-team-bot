"""
Google Calendar API wrapper
"""
import logging
from datetime import datetime, timedelta
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
            self.service = build('calendar', 'v3', credentials=credentials)
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
            now = datetime.utcnow().isoformat() + 'Z'
            future = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'

            result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=now,
                timeMax=future,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = result.get('items', [])
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
