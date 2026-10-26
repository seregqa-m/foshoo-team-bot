import { getInitialPlanningMonth } from './navigation';

test('reads the Telegram launch parameter and the URL fallback', () => {
  expect(getInitialPlanningMonth({ initDataUnsafe: { start_param: 'planning_2026-12' } }, '')).toBe('2026-12');
  expect(getInitialPlanningMonth({}, '?tgWebAppStartParam=planning_2027-01')).toBe('2027-01');
  expect(getInitialPlanningMonth({ initDataUnsafe: { start_param: 'planning_2026-12' } }, '?tgWebAppStartParam=planning_2027-01')).toBe('2026-12');
});

test.each(['', 'finance', 'planning_2026-00', 'planning_2026-13', 'planning_0000-01', 'planning_2026-1', 'planning_2026-12_extra'])(
  'ignores an unsupported or invalid launch parameter: %s', start_param => {
    expect(getInitialPlanningMonth({ initDataUnsafe: { start_param } }, '')).toBe('');
  },
);
