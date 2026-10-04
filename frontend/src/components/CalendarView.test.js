import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import CalendarView from './CalendarView';
import client from '../api/client';
import * as calendarApi from '../api/calendar';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock('../api/calendar', () => ({ getEvents: jest.fn(), launchPoll: jest.fn() }));
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
  calendarApi.launchPoll.mockReset();
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

const chooseShowError = (shows = [
  { id: 10, name: 'Гамлет', telegram_chat_id: -100111, chat_title: 'Репетиции Гамлета' },
  { id: 11, name: 'Урод', telegram_chat_id: -100222, chat_title: 'Урод' },
  { id: 12, name: 'Без чата', telegram_chat_id: null },
]) => ({ response: { status: 409, data: { detail: { code: 'show_required', shows } } } });

test('offers existing shows for an unknown rehearsal and sends only after selection', async () => {
  calendarApi.getEvents.mockResolvedValue({ data: { events: [
    { ...event(7, 'Разбор [Реп]', '19:00', '21:00'), event_type: 'rehearsal' },
  ] } });
  calendarApi.launchPoll.mockRejectedValueOnce(chooseShowError()).mockResolvedValue({ data: { status: 'sent' } });
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  await act(async () => button('🗳️ Опрос').click());
  expect(calendarApi.launchPoll).toHaveBeenCalledWith(7, 42, null);
  const select = container.querySelector('#poll-show-7');
  expect([...select.options].map(o => o.textContent)).toEqual([
    'Выберите спектакль', 'Гамлет', 'Урод', 'Без чата — чат не настроен',
  ]);
  expect(select.options[3].disabled).toBe(true);
  expect(button('Отправить опрос').disabled).toBe(true);
  await act(async () => { select.value = '10'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(container.textContent).toContain('Опрос и напоминания пойдут в чат «Репетиции Гамлета»');
  expect(calendarApi.launchPoll).toHaveBeenCalledTimes(1);
  await act(async () => button('Отправить опрос').click());
  expect(calendarApi.launchPoll).toHaveBeenLastCalledWith(7, 42, 10);
  expect(container.querySelector('#poll-show-7')).toBeNull();
  expect(calendarApi.getEvents).toHaveBeenCalledTimes(2);
});

test('cancelling show selection sends no poll', async () => {
  calendarApi.launchPoll.mockRejectedValueOnce(chooseShowError());
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  await act(async () => button('🗳️ Опрос').click());
  await act(async () => button('Отмена').click());
  expect(container.querySelector('select')).toBeNull();
  expect(button('🗳️ Опрос')).toBeDefined();
  expect(calendarApi.launchPoll).toHaveBeenCalledTimes(1);
});

test('empty show catalog explains where to configure it', async () => {
  calendarApi.launchPoll.mockRejectedValueOnce(chooseShowError([]));
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  await act(async () => button('🗳️ Опрос').click());
  expect(container.textContent).toContain('Список спектаклей пуст');
  expect(button('Отправить опрос')).toBeUndefined();
});

test('keeps selection and displays a send failure so it can be retried', async () => {
  calendarApi.launchPoll.mockRejectedValueOnce(chooseShowError())
    .mockRejectedValueOnce({ response: { data: { detail: 'Telegram отклонил отправку' } } });
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  await act(async () => button('🗳️ Опрос').click());
  const select = container.querySelector('select');
  await act(async () => { select.value = '11'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => button('Отправить опрос').click());
  expect(container.textContent).toContain('Telegram отклонил отправку');
  expect(select.value).toBe('11');
  expect(button('Отправить опрос').disabled).toBe(false);
});

test('recognized show sends immediately and saved selection is visible after reload', async () => {
  calendarApi.getEvents.mockResolvedValue({ data: { events: [
    { ...event(7, 'Разбор [Реп]', '19:00', '21:00'), event_type: 'rehearsal', poll_show_name: 'Гамлет' },
  ] } });
  calendarApi.launchPoll.mockResolvedValue({ data: { status: 'sent' } });
  await act(async () => root.render(<CalendarView userId={42} isAdmin />));
  expect(container.querySelector('.event-body').textContent).toContain('Гамлет');
  await act(async () => button('🗳️ Опрос').click());
  expect(calendarApi.launchPoll).toHaveBeenCalledWith(7, 42, null);
  expect(container.querySelector('select')).toBeNull();
});

test('non-admin has no launch button', async () => {
  await act(async () => root.render(<CalendarView userId={42} />));
  expect(button('🗳️ Опрос')).toBeUndefined();
});
