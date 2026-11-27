import React from 'react';

const day = value => new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`));

export default function RepertoireAlternatives({ variants, selected, recommendedId, complete, disabled, onSelect }) {
  if (!variants.length || selected?.manual) return null;
  const index = Math.max(0, variants.findIndex(v => v.id === selected?.id));
  const current = variants[index];
  const recommended = current.id === (recommendedId || variants[0].id);
  return <section className="repertoire-alternatives" aria-label="Варианты расписания">
    <div className="repertoire-carousel">
      <button type="button" className="btn btn-secondary" aria-label="Предыдущий вариант" disabled={disabled || index === 0} onClick={() => onSelect(variants[index - 1])}>←</button>
      <div aria-live="polite"><strong>Вариант {index + 1} из {variants.length}</strong><small>{recommended ? 'Рекомендованный' : 'Альтернатива'}</small></div>
      <button type="button" className="btn btn-secondary" aria-label="Следующий вариант" disabled={disabled || index === variants.length - 1} onClick={() => onSelect(variants[index + 1])}>→</button>
    </div>
    {recommended ? <p className="repertoire-note">Максимум показов, затем приоритет нагрузке актёров и разносу.{!complete && ' Лучший среди найденных; расчёт продолжается.'}</p>
      : <div className="repertoire-differences"><p>Отличия от рекомендованного:</p><ul>{(current.changes || []).map(change => <li key={change.key}>
        {change.name}: {change.from.length ? change.from.map(day).join(', ') : 'добавлен'} → {change.to.length ? change.to.map(day).join(', ') : 'убран'}
      </li>)}</ul></div>}
    {current.retained && <p className="repertoire-note">Ваш выбор сохранён, хотя подборка уже обновилась.</p>}
    <p className="repertoire-note">Варианты отличаются датами и спектаклями. Состав подбирается по ответам.</p>
  </section>;
}
