import React, { useState } from 'react';

export default function RepertoireShowTime({ entry, disabled, onChange }) {
  const initial = entry.start_time?.slice(11, 16) || '';
  const [value, setValue] = useState(initial);
  const valid = /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
  return <form onSubmit={event => { event.preventDefault(); if (valid && !disabled && value !== initial) onChange(value); }}>
    <label className="repertoire-field">Начало показа
      <input className="form-input" type="time" step="60" required aria-label={`Начало ${entry.name}, ${entry.date}`}
        value={value} disabled={disabled} onChange={event => setValue(event.target.value)} />
    </label>
    <button type="submit" className="btn btn-secondary" disabled={disabled || !valid || value === initial}>Применить время</button>
    <p className="repertoire-note">Только для этого показа. Перед сохранением проверим пересечения с календарём.</p>
  </form>;
}
