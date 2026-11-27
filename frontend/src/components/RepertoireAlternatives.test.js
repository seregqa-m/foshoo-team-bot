import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import RepertoireAlternatives from './RepertoireAlternatives';

let container, root;
const variants = [{ id: 'best', changes: [] }, { id: 'other', changes: [
  { key: 'a', name: 'Калий', from: ['2027-01-17'], to: ['2027-01-30'] },
  { key: 'b', name: 'Микрополь', from: [], to: ['2027-01-24'] },
] }];
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const render = props => act(() => root.render(<RepertoireAlternatives variants={variants} selected={variants[0]} recommendedId="best" complete onSelect={jest.fn()} {...props} />));

test('arrows select exact variants and stop at both ends', () => {
  const onSelect = jest.fn(); render({ onSelect });
  expect(container.querySelector('[aria-label="Предыдущий вариант"]').disabled).toBe(true);
  act(() => container.querySelector('[aria-label="Следующий вариант"]').click());
  expect(onSelect).toHaveBeenCalledWith(variants[1]);
  render({ selected: variants[1] });
  expect(container.querySelector('[aria-label="Следующий вариант"]').disabled).toBe(true);
  expect(container.textContent).toContain('Калий: 17 янв. → 30 янв.');
  expect(container.textContent).toContain('Микрополь: добавлен → 24 янв.');
});

test('one recommendation is not padded and manual drafts do not silently switch', () => {
  render({ variants: [variants[0]] });
  expect(container.textContent).toContain('Вариант 1 из 1');
  expect([...container.querySelectorAll('button')].every(b => b.disabled)).toBe(true);
  render({ selected: { id: 'manual', manual: true } });
  expect(container.textContent).toBe('');
});

test('ongoing search and retention explain recommendation changes', () => {
  render({ complete: false });
  expect(container.textContent).toContain('среди найденных');
  render({ variants: [variants[0], { ...variants[1], retained: true }], selected: variants[1] });
  expect(container.textContent).toContain('Ваш выбор сохранён');
});
