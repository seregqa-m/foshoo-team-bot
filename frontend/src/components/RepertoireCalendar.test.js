import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import RepertoireCalendar from './RepertoireCalendar';

let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const entries = [{ date: '2028-02-06', key: '1', name: 'Урод', fixed: false }, { date: '2028-02-20', key: '2', name: 'Любовь Громова', fixed: true }];
const render = ({ key = 'calendar', ...props } = {}) => act(() => root.render(<RepertoireCalendar key={key} month="2028-02" entries={entries} pins={[{ day: '2028-02-06', key: '1' }]} renderEntry={e => <p key={e.key}>Состав {e.name}</p>} {...props} />));

test('renders a Monday-first leap month with complete names accessible and in legend', () => {
  render();
  const grid = container.querySelector('.repertoire-calendar-grid');
  expect([...grid.children].slice(0, 7).map(e => e.textContent)).toEqual(['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']);
  expect(grid.children[7].getAttribute('aria-hidden')).toBe('true');
  expect(grid.children[8].getAttribute('data-date')).toBe('2028-02-01');
  expect(grid.querySelectorAll('button')).toHaveLength(29);
  expect(container.querySelector('[data-date="2028-02-06"]').getAttribute('aria-label')).toContain('Урод, закреплено');
  expect(container.querySelector('[data-date="2028-02-20"]').getAttribute('aria-label')).toContain('Любовь Громова, уже в расписании');
  expect(container.querySelector('.repertoire-calendar-legend').textContent).toContain('ЛГ — Любовь Громова');
});

test('only selected day details are expanded and empty days are explicit', () => {
  render();
  const detail = () => container.querySelector('#repertoire-day-detail').textContent;
  expect(detail()).toBe('Состав Урод');
  act(() => container.querySelector('[data-date="2028-02-20"]').click());
  expect(detail()).toBe('Состав Любовь Громова');
  expect(container.querySelector('[data-date="2028-02-20"]').getAttribute('aria-pressed')).toBe('true');
  act(() => container.querySelector('[data-date="2028-02-21"]').click());
  expect(detail()).toContain('показов нет');
});

test('changing month resets selection and aligns a Sunday month start', () => {
  render();
  render({ key: 'new-month', month: '2028-10', entries: [] });
  const grid = container.querySelector('.repertoire-calendar-grid');
  expect(grid.children[13].getAttribute('data-date')).toBe('2028-10-01');
  expect(grid.querySelectorAll('button')).toHaveLength(31);
  expect(container.querySelector('[data-date="2028-10-01"]').getAttribute('aria-pressed')).toBe('true');
});
