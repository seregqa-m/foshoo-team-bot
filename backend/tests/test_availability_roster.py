import os
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://', 'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    import main
    from core.database import Base
    from modules.availability.models import AvailabilityCampaign, AvailabilityPoll, AvailabilityPollOption
    from modules.availability.roster import unregistered_cast_members, queue_cast_memberships
    from modules.availability.router import get_non_voters, ping_non_voters
    from modules.attendance.models import VoterRegistration, ChatParticipant, DayAnswer
    from modules.theater.models import TheaterShow, TheaterShowAlias
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class AvailabilityRosterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        session_patch = patch('core.database.SessionLocal', self.Session)
        session_patch.start()
        self.addCleanup(session_patch.stop)
        self.membership = AsyncMock(return_value=type('Member', (), {'status': 'member'})())
        member_patch = patch('bot.bot.get_chat_member', self.membership)
        member_patch.start()
        self.addCleanup(member_patch.stop)
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
                                         'reason': 'not_registered', 'can_ping': False, 'chat_id': -1001,
                                         'missing_dates': None, 'answered_count': None, 'total_dates': 1}])

    async def test_registered_members_stay_in_existing_nonvoter_roster(self):
        self.register()
        self.assertEqual(self.members(), [])
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient') as client:
            client.return_value.get_attendance_roster.return_value = self.source
            result = await get_non_voters(self.db, self.campaign.id)
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

    async def test_api_shows_unregistered_people_without_adding_them_to_ping_recipients(self):
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient') as client:
            client.return_value.get_attendance_roster.return_value = self.source
            result = await get_non_voters(self.db, self.campaign.id)
        self.assertEqual(result['participants'], [])
        self.assertEqual(result['non_voters'], [])
        self.assertEqual(result['unregistered_participants'][0]['username'], 'q_poo')
        self.assertIsNone(result['roster_warning'])

    async def test_failed_sheets_read_is_not_reported_as_a_complete_roster(self):
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient', side_effect=RuntimeError('offline')):
            result = await get_non_voters(self.db, self.campaign.id)
        self.assertTrue(result['roster_warning'])

    async def response(self):
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient') as client:
            client.return_value.get_attendance_roster.return_value = self.source
            return await get_non_voters(self.db, self.campaign.id)

    def other_chat(self):
        self.db.add(TheaterShow(name='Другой спектакль', normalized_name='другой спектакль', telegram_chat_id=-1002))
        self.db.add(VoterRegistration(user_id=42, username='q_poo', display_name='Никита',
                                      telegram_chat_id=-1002, membership_status='member'))
        self.db.add(ChatParticipant(chat_id=-1002, user_id=42, status='member'))
        self.db.commit()

    async def test_other_chat_voter_is_discovered_verified_and_can_be_pinged(self):
        self.other_chat()
        result = await self.response()
        self.membership.assert_awaited_once_with(-1001, 42)
        self.assertEqual(result['unregistered_participants'], [])
        self.assertEqual(result['participants'][0]['user_id'], 42)
        self.assertEqual(result['participants'][0]['missing_dates'], ['2026-12-23'])
        self.assertEqual(self.db.query(DayAnswer).count(), 0)

    async def test_failed_verification_preserves_shared_answers_and_never_grants_membership(self):
        self.other_chat()
        poll = self.campaign.polls[0]
        self.db.add(AvailabilityPollOption(poll_id=poll.id, option_index=1, selected_date=date(2026, 12, 24)))
        self.db.add(DayAnswer(user_id=42, day=date(2026, 12, 23), answer='no', source='other-chat'))
        self.db.commit()
        self.membership.side_effect = TimeoutError()
        result = await self.response()
        self.assertEqual(result['participants'], [])
        row = result['unregistered_participants'][0]
        self.assertEqual(row['reason'], 'membership_unverified')
        self.assertEqual(row['missing_dates'], ['2026-12-24'])
        self.assertEqual(row['answered_count'], 1)
        self.assertTrue(result['roster_warning'])
        self.assertEqual(self.db.get(ChatParticipant, (-1001, 42)).status, 'pending')
        self.membership.side_effect = None
        self.assertEqual((await self.response())['unregistered_participants'], [])

    async def test_confirmed_nonmember_has_distinct_reason(self):
        self.other_chat()
        self.membership.return_value.status = 'left'
        result = await self.response()
        self.assertEqual(result['participants'], [])
        self.assertEqual(result['unregistered_participants'][0]['reason'], 'not_member')

    async def test_other_chat_answers_cover_all_dates_without_target_membership(self):
        self.other_chat()
        self.db.add(DayAnswer(user_id=42, day=date(2026, 12, 23), answer='yes', source='other-chat'))
        self.db.commit()
        self.membership.return_value.status = 'left'
        result = await self.response()
        self.assertEqual(result['participants'], [])
        self.assertEqual(result['unregistered_participants'], [])

    async def test_ping_discovers_members_even_without_opening_the_list_and_rechecks_before_send(self):
        from fastapi import HTTPException
        self.other_chat()
        self.campaign.polls[0].telegram_message_id = 123
        self.db.commit()
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient') as client, patch('bot.bot.send_message', AsyncMock()) as send:
            client.return_value.get_attendance_roster.return_value = self.source
            result = await ping_non_voters(self.db, self.campaign.id)
            self.assertEqual(result['count'], 1)
            self.assertEqual(send.call_args.kwargs['chat_id'], -1001)
            self.assertIn('tg://user?id=42', send.call_args.kwargs['text'])
            send.reset_mock()
            self.membership.side_effect = TimeoutError()
            with self.assertRaises(HTTPException):
                await ping_non_voters(self.db, self.campaign.id)
            send.assert_not_awaited()
            self.membership.side_effect = None
            self.membership.return_value.status = 'left'
            self.assertEqual((await ping_non_voters(self.db, self.campaign.id))['count'], 0)
            send.assert_not_awaited()

    async def test_missing_dates_merge_across_verified_groups(self):
        self.other_chat()
        self.campaign.show_names = '["Урод", "Другой спектакль"]'
        self.source['casts'].append(['Другой спектакль', 'Роль', 'Никита Мягков'])
        poll = AvailabilityPoll(campaign_id=self.campaign.id, telegram_chat_id=-1002)
        self.db.add(poll); self.db.flush()
        self.db.add(AvailabilityPollOption(poll_id=poll.id, option_index=0, selected_date=date(2026, 12, 24)))
        self.db.commit(); self.db.expire_all()
        result = await self.response()
        self.assertEqual(len(result['participants']), 1)
        self.assertEqual(result['participants'][0]['missing_dates'], ['2026-12-23', '2026-12-24'])

    def test_ambiguous_or_claimed_identity_never_creates_memberships(self):
        self.other_chat()
        self.source['troupe'].append(['Другой человек'] + [''] * 8 + ['different', '42'])
        queue_cast_memberships(self.db, self.campaign, self.source)
        self.assertIsNone(self.db.get(ChatParticipant, (-1001, 42)))
        self.assertEqual(self.members()[0]['reason'], 'ambiguous_identity')

    def test_answers_only_need_to_cover_dates_of_the_actors_groups(self):
        self.register(member=False)
        self.db.add(TheaterShow(name='Другой спектакль', normalized_name='другой спектакль', telegram_chat_id=-1002))
        self.campaign.show_names = '["Урод", "Другой спектакль"]'
        poll = AvailabilityPoll(campaign_id=self.campaign.id, telegram_chat_id=-1002)
        self.db.add(poll); self.db.flush()
        self.db.add(AvailabilityPollOption(poll_id=poll.id, option_index=0, selected_date=date(2026, 12, 24)))
        self.db.add(DayAnswer(user_id=42, day=date(2026, 12, 23), answer='unknown', source='other-chat'))
        self.db.commit(); self.db.expire_all()
        self.assertFalse(any(row['name'] == 'Никита Мягков' for row in self.members()))
        self.db.get(DayAnswer, (42, date(2026, 12, 23))).answer = 'retracted'
        self.db.commit()
        row = next(row for row in self.members() if row['name'] == 'Никита Мягков')
        self.assertEqual(row['missing_dates'], ['2026-12-23'])

    def test_membership_in_one_cast_group_does_not_hide_another(self):
        self.register()
        self.db.add(TheaterShow(name='Другой спектакль', normalized_name='другой спектакль', telegram_chat_id=-1002))
        self.campaign.show_names = '["Урод", "Другой спектакль"]'
        self.source['casts'].append(['Другой спектакль', 'Роль', 'Никита Мягков'])
        poll = AvailabilityPoll(campaign_id=self.campaign.id, telegram_chat_id=-1002)
        self.db.add(poll); self.db.flush()
        self.db.add(AvailabilityPollOption(poll_id=poll.id, option_index=0, selected_date=date(2026, 12, 24)))
        self.db.commit(); self.db.expire_all()
        row = next(row for row in self.members() if row['name'] == 'Никита Мягков')
        self.assertEqual(row['show_names'], ['Другой спектакль'])
        self.assertEqual(row['missing_dates'], ['2026-12-24'])

    def test_assistant_context_exposes_known_nonvoters_and_respects_other_chat_answers(self):
        from modules.assistant.context import _collect_availability_campaign
        self.register()
        self.assertEqual(_collect_availability_campaign(self.db, {})['non_voters'], ['q_poo'])
        self.db.add(DayAnswer(user_id=42, day=date(2026, 12, 23), answer='no', source='other-chat'))
        self.db.commit()
        self.assertEqual(_collect_availability_campaign(self.db, {})['non_voters'], [])

    async def test_old_block_ping_uses_only_its_dates_after_a_new_block_is_created(self):
        from modules.availability.router import list_campaigns
        self.register()
        self.campaign.polls[0].telegram_message_id = 11
        # Legacy rows have no request key, per-publication names or delivery state.
        self.campaign.request_key = None
        self.campaign.polls[0].show_names = None
        self.campaign.polls[0].delivery_state = None
        newer = AvailabilityCampaign(month='2026-12', show_names='["Урод"]')
        self.db.add(newer); self.db.flush()
        poll = AvailabilityPoll(campaign_id=newer.id, telegram_chat_id=-1001, telegram_message_id=22)
        self.db.add(poll); self.db.flush()
        self.db.add(AvailabilityPollOption(poll_id=poll.id, option_index=0, selected_date=date(2026, 12, 24)))
        self.db.add(DayAnswer(user_id=42, day=date(2026, 12, 24), answer='yes', source='other-chat'))
        self.db.commit()
        blocks = list_campaigns(self.db)['campaigns']
        old_block = next(block for block in blocks if block['id'] == self.campaign.id)
        self.assertEqual(old_block['polls'][0]['tg_link'], 'https://t.me/c/1/11')
        self.assertEqual(old_block['polls'][0]['show_names'], ['Урод'])
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient') as client, patch('bot.bot.send_message', AsyncMock()) as send:
            client.return_value.get_attendance_roster.return_value = self.source
            self.assertEqual((await get_non_voters(self.db, newer.id))['participants'], [])
            old = await get_non_voters(self.db, self.campaign.id)
            self.assertEqual(old['participants'][0]['missing_dates'], ['2026-12-23'])
            self.assertEqual((await ping_non_voters(self.db, newer.id))['count'], 0)
            send.assert_not_awaited()
            self.assertEqual((await ping_non_voters(self.db, self.campaign.id))['count'], 1)
            self.assertIn('/11', send.call_args.kwargs['text'])
            self.assertNotIn('/22', send.call_args.kwargs['text'])

    async def test_assistant_can_select_a_retained_block_and_preview_its_id(self):
        from modules.assistant.context import _collect_availability_campaign
        from modules.assistant.tools import PING_NON_VOTERS
        newer = AvailabilityCampaign(month='2027-01', show_names='["Урод"]')
        self.db.add(newer); self.db.commit()
        context = _collect_availability_campaign(self.db, {})
        self.assertEqual([block['id'] for block in context['recent_blocks']], [newer.id, self.campaign.id])
        self.assertEqual(context['recent_blocks'][1]['dates'], ['2026-12-23'])
        args = {'campaign_id': self.campaign.id}
        self.assertIn(str(self.campaign.id), PING_NON_VOTERS.preview_builder(args)['lines'][0])
        self.assertEqual(PING_NON_VOTERS.safety_level, 'confirm')
        with patch('modules.availability.router.ping_non_voters', AsyncMock(return_value={'count': 0})) as endpoint:
            await PING_NON_VOTERS.handler(self.db, args, {})
            endpoint.assert_awaited_once_with(db=self.db, campaign_id=self.campaign.id)
            from fastapi import HTTPException
            endpoint.reset_mock()
            with self.assertRaises(HTTPException):
                await PING_NON_VOTERS.handler(self.db, {}, {})
            endpoint.assert_not_awaited()
