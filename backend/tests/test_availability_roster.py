import os
import unittest
from datetime import date
from unittest.mock import patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://', 'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    import main
    from core.database import Base
    from modules.availability.models import AvailabilityCampaign, AvailabilityPoll, AvailabilityPollOption
    from modules.availability.roster import unregistered_cast_members
    from modules.availability.router import get_non_voters
    from modules.attendance.models import VoterRegistration, ChatParticipant, DayAnswer
    from modules.theater.models import TheaterShow, TheaterShowAlias
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class AvailabilityRosterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        show = TheaterShow(name='Урод', normalized_name='урод', telegram_chat_id=-1001)
        self.db.add(show); self.db.flush()
        self.db.add(TheaterShowAlias(normalized_name='старое название', show_id=show.id))
        self.campaign = AvailabilityCampaign(month='2026-12', show_names='["Урод"]')
        self.db.add(self.campaign); self.db.flush()
        poll = AvailabilityPoll(campaign_id=self.campaign.id, telegram_chat_id=-1001, show_names='["Урод"]')
        self.db.add(poll); self.db.flush()
        self.db.add(AvailabilityPollOption(poll_id=poll.id, option_index=0, selected_date=date(2026, 12, 23)))
        self.db.commit()
        self.source = {'troupe': [['Имя'] + [''] * 8 + ['Username', 'Telegram ID'],
                                  ['Никита Мягков'] + [''] * 8 + ['Q_poo', '']],
                       'casts': [['Спектакль', 'Роль', 'Актёр'], ['Старое название', 'Врач', 'Никита Мягков'],
                                 ['Урод', 'Врач 2', 'Никита Мягков'], ['Другой спектакль', 'Роль', 'Другой актёр']]}

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def members(self):
        return unregistered_cast_members(self.db, self.campaign, self.source)

    def register(self, *, username='q_poo', member=True):
        self.db.add(VoterRegistration(user_id=42, username=username, display_name='Никита', actor_name='Никита Мягков',
                                      telegram_chat_id=-1001, membership_status='member'))
        if member:
            self.db.add(ChatParticipant(chat_id=-1001, user_id=42, status='member'))
        self.db.commit()

    def test_unregistered_cast_member_is_visible_once_and_cannot_be_pinged(self):
        self.assertEqual(self.members(), [{'name': 'Никита Мягков', 'username': 'q_poo', 'show_names': ['Урод'],
                                         'reason': 'not_registered', 'can_ping': False}])

    def test_registered_members_stay_in_existing_nonvoter_roster(self):
        self.register()
        self.assertEqual(self.members(), [])
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient') as client:
            client.return_value.get_attendance_roster.return_value = self.source
            result = get_non_voters(self.db, self.campaign.id)
        self.assertEqual(result['participants'][0]['user_id'], 42)
        self.assertEqual(result['unregistered_participants'], [])

    def test_known_id_survives_username_change_but_name_alone_never_binds_identity(self):
        self.register(username='new_username')
        self.assertEqual(len(self.members()), 1)
        self.source['troupe'][1][10] = '42'
        self.assertEqual(self.members(), [])

    def test_duplicate_sheet_username_is_flagged_instead_of_linking(self):
        self.register()
        self.source['troupe'].append(['Другой человек'] + [''] * 8 + ['q_poo', ''])
        self.assertEqual(self.members()[0]['reason'], 'ambiguous_identity')

    def test_membership_is_separate_from_registration_and_common_answers_are_respected(self):
        self.register(member=False)
        self.assertEqual(self.members()[0]['reason'], 'membership_unverified')
        self.db.add(DayAnswer(user_id=42, day=date(2026, 12, 23), answer='no', source='other-chat'))
        self.db.commit()
        self.assertEqual(self.members(), [])

    def test_api_shows_unregistered_people_without_adding_them_to_ping_recipients(self):
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient') as client:
            client.return_value.get_attendance_roster.return_value = self.source
            result = get_non_voters(self.db, self.campaign.id)
        self.assertEqual(result['participants'], [])
        self.assertEqual(result['non_voters'], [])
        self.assertEqual(result['unregistered_participants'][0]['username'], 'q_poo')
        self.assertIsNone(result['roster_warning'])

    def test_failed_sheets_read_is_not_reported_as_a_complete_roster(self):
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient', side_effect=RuntimeError('offline')):
            result = get_non_voters(self.db, self.campaign.id)
        self.assertTrue(result['roster_warning'])
