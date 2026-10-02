import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import CalendarView from './CalendarView';
import client from '../api/client';
import * as calendarApi from '../api/calendar';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock('../api/calendar', () => ({ getEvents: jest.fn() }));
jest.mock('./PlanningView', () => () => null);

let root, container;
const event = (id, title, start, end) => ({
  id, title, start_time: `2026-10-01T${start}:00`, end_time: `2026-10-01T${end}:00`,
});
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
const titles = () => [...container.querySelectorAll('.event-title')].map(el => el.textContent);

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.useFakeTimers().setSystemTime(new Date('2026-10-01T15:00:00'));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/shows') ? { shows: ['Гамлет', ''] } : {} }));
  calendarApi.getEvents.mockResolvedValue({ data: { events: [
    event(1, 'Труппа 1 — вчерашний разбор', '10:00', '11:00'),
    event(2, 'Труппа 1 — текущая репетиция', '14:00', '16:00'),
    event(3, 'Труппа 1 — ГАМЛЕТ', '19:00', '21:00'),
    event(4, 'Труппа 2', '17:00', '18:00'),
    event(5, 'Лаба', '18:00', '19:00'),
  ] } });
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  jest.useRealTimers();
  jest.clearAllMocks();
});

test('keeps past and ongoing events, fading only ended events in both views', async () => {
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  expect(calendarApi.getEvents).toHaveBeenCalledWith(60, true);
  expect(titles()).toEqual(['Труппа 1 — текущая репетиция', 'Труппа 1 — вчерашний разбор']);
  const cards = container.querySelectorAll('.event-card');
  expect(cards[0].style.opacity).toBe('1');
  expect(cards[1].style.opacity).toBe('0.5');
  expect(cards[1].textContent).toContain('Завершено');
  expect(cards[1].textContent).not.toContain('🗳️ Опрос');
  const blocks = container.querySelectorAll('rect[fill-opacity]');
  expect(blocks[0].getAttribute('fill-opacity')).toBe('0.35');
  expect(blocks[1].getAttribute('fill-opacity')).toBe('0.9');
  await act(async () => cards[1].querySelector('button').click());
  expect(container.querySelector('.modal-title').textContent).toBe('Редактировать');
});

test('puts known show titles in a separate group with a matching color', async () => {
  await act(async () => root.render(<CalendarView trouFilter="ТРУППА 1" />));
  expect(titles()).toHaveLength(2);
  await act(async () => button('Спектакли').click());
  expect(titles()).toEqual(['Труппа 1 — ГАМЛЕТ']);
  expect(container.querySelectorAll('rect[fill-opacity]')[2].getAttribute('fill')).toBe('#6EE7B7');
  await act(async () => button('Труппа 2').click());
  expect(titles()).toEqual(['Труппа 2']);
  await act(async () => button('Лаба').click());
  expect(titles()).toEqual(['Лаба']);
  await act(async () => button('Все').click());
  expect(titles()).toHaveLength(5);
});

test('fades an event when it ends without reloading the page', async () => {
  await act(async () => root.render(<CalendarView />));
  act(() => jest.advanceTimersByTime(60 * 60 * 1000));
  const ongoing = [...container.querySelectorAll('.event-card')].find(el => el.textContent.includes('текущая репетиция'));
  expect(ongoing.style.opacity).toBe('0.5');
  expect(container.querySelectorAll('rect[fill-opacity]')[1].getAttribute('fill-opacity')).toBe('0.35');
});

test('shows the October 11 performance alias in the show filter and calendar', async () => {
  calendarApi.getEvents.mockResolvedValue({ data: { events: [{
    id: 11, title: 'ЛГ[Спект]', start_time: '2026-10-11T19:00:00', end_time: '2026-10-11T21:00:00',
    event_type: 'performance', show_name: 'Любовь Громова',
  }] } });
  client.get.mockResolvedValue({ data: {} }); // Explicit types work without the Sheets catalog.
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  expect(titles()).toEqual([]);
  await act(async () => button('Спектакли').click());
  expect(titles()).toEqual(['ЛГ[Спект]']);
  expect(container.querySelector('.event-card').textContent).toContain('Любовь Громова');
  expect(container.querySelector('.event-card').textContent).not.toContain('🗳️ Опрос');
  await act(async () => button('›').click());
  expect(container.querySelector('rect[fill-opacity]').getAttribute('fill')).toBe('#6EE7B7');
});

test('explicit rehearsal type overrides a known show name and keeps troupe color', async () => {
  calendarApi.getEvents.mockResolvedValue({ data: { events: [
    { ...event(1, 'Труппа 1 — Гамлет[Реп]', '19:00', '21:00'), event_type: 'rehearsal' },
    { ...event(2, 'ЛГ[Реп]', '19:00', '21:00'), event_type: 'rehearsal', show_name: 'Любовь Громова' },
    { ...event(3, 'Неизвестная премьера[Спект]', '19:00', '21:00'), event_type: 'performance' },
  ] } });
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  expect(titles()).toEqual(['Труппа 1 — Гамлет[Реп]', 'ЛГ[Реп]']);
  expect(container.querySelector('.event-card').textContent).toContain('🗳️ Опрос');
  expect(container.querySelector('rect[fill-opacity]').getAttribute('fill')).toBe('#C4B5FD');
  await act(async () => button('Спектакли').click());
  expect(titles()).toEqual(['Неизвестная премьера[Спект]']);
});
