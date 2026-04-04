import React, { useState, useEffect } from 'react';
import client from '../api/client';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend
} from 'recharts';

class ChartErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(e) { return { error: e?.message || String(e) }; }
  render() {
    if (this.state.error) {
      return <div style={{ fontSize: 11, color: 'red', padding: 8, wordBreak: 'break-all' }}>Chart error: {this.state.error}</div>;
    }
    return this.props.children;
  }
}

function SimpleBarChart({ data }) {
  const [tooltip, setTooltip] = useState(null);
  const h = 160, padL = 36, padB = 28, padT = 8, padR = 8;
  const max = Math.max(...data.flatMap(d => [d.income, d.expense]), 1);
  const barW = Math.max(4, Math.min(16, (300 - padL - padR) / (data.length * 2 + data.length * 0.5) | 0));
  const gap = Math.max(2, barW * 0.3 | 0);
  const groupW = barW * 2 + gap;
  const totalW = padL + data.length * groupW + (data.length - 1) * gap + padR;
  const chartH = h - padT - padB;
  const fy = v => padT + chartH - (v / max) * chartH;

  return (
    <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
      <div style={{ position: 'relative', display: 'inline-block' }}>
        {tooltip && (
          <div style={{
            position: 'absolute', top: 0, left: tooltip.x, transform: 'translateX(-50%)',
            background: '#111', color: '#fff', borderRadius: 6, padding: '4px 8px',
            fontSize: 11, pointerEvents: 'none', whiteSpace: 'nowrap', zIndex: 10,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{tooltip.period}</div>
            <div>Доход: {tooltip.income.toLocaleString('ru')} ₽</div>
            <div>Расход: {tooltip.expense.toLocaleString('ru')} ₽</div>
          </div>
        )}
        <svg width={totalW} height={h}>
          {/* Y-axis */}
          {[0, 0.5, 1].map(t => {
            const y = padT + chartH * (1 - t);
            const val = max * t;
            return (
              <g key={t}>
                <line x1={padL} x2={totalW - padR} y1={y} y2={y} stroke="#eee" strokeWidth={1} />
                <text x={padL - 4} y={y + 4} textAnchor="end" fontSize={9} fill="#999">
                  {val >= 1000 ? `${(val / 1000).toFixed(0)}к` : val.toFixed(0)}
                </text>
              </g>
            );
          })}
          {/* Bars */}
          {data.map((d, i) => {
            const x = padL + i * (groupW + gap);
            const ih = Math.max(2, (d.income / max) * chartH);
            const eh = Math.max(2, (d.expense / max) * chartH);
            return (
              <g key={d.period}
                onMouseEnter={() => setTooltip({ ...d, x: x + groupW / 2 })}
                onMouseLeave={() => setTooltip(null)}
                onTouchStart={() => setTooltip({ ...d, x: x + groupW / 2 })}
                onTouchEnd={() => setTimeout(() => setTooltip(null), 1500)}
                style={{ cursor: 'pointer' }}
              >
                <rect x={x} y={fy(d.income)} width={barW} height={ih} fill="#111" rx={2} />
                <rect x={x + barW + gap} y={fy(d.expense)} width={barW} height={eh} fill="#ccc" rx={2} />
                {i % Math.ceil(data.length / 6) === 0 && (
                  <text x={x + groupW / 2} y={h - 6} textAnchor="middle" fontSize={9} fill="#999">
                    {d.period.length > 7 ? d.period.slice(0, 5) : d.period}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div style={{ display: 'flex', gap: 12, paddingLeft: padL, marginTop: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#666' }}>
          <div style={{ width: 10, height: 10, background: '#111', borderRadius: 2 }} /> Доход
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#666' }}>
          <div style={{ width: 10, height: 10, background: '#ccc', borderRadius: 2 }} /> Расход
        </div>
      </div>
    </div>
  );
}

const EMPTY_EXPENSE = { project: '', amount: '', what: '', expense_type: '', comment: '', who: '' };
const EMPTY_INCOME  = { project: '', amount: '', what: '', comment: '' };

export default function FinanceView({ username }) {
  const [balance, setBalance] = useState(null);
  const [meta, setMeta] = useState({ projects: [], expense_types: [], actors: [] });
  const [modal, setModal] = useState(null); // 'expense' | 'income' | null
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [chartPeriod, setChartPeriod] = useState('month');
  const [chartData, setChartData] = useState([]);

  useEffect(() => {
    client.get('/api/finance/balance').then(r => setBalance(r.data.balance)).catch(() => {});
    client.get('/api/finance/meta').then(r => setMeta(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    client.get('/api/finance/chart', { params: { period: chartPeriod } })
      .then(r => setChartData(r.data.data))
      .catch(() => {});
  }, [chartPeriod]);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const openExpense = () => {
    setForm({ ...EMPTY_EXPENSE });
    setModal('expense');
    setError(null);
    if (username) {
      client.get('/api/finance/whoami', { params: { username } })
        .then(r => setForm(f => ({ ...f, who: r.data.name || '' })))
        .catch(() => {});
    }
  };
  const openIncome  = () => { setForm({ ...EMPTY_INCOME });  setModal('income');  setError(null); };
  const closeModal  = () => { setModal(null); setError(null); };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.project || !form.amount || !form.what) {
      setError('Заполните обязательные поля');
      return;
    }
    if (modal === 'expense' && !form.expense_type) {
      setError('Укажите тип траты');
      return;
    }
    try {
      setSaving(true);
      setError(null);
      if (modal === 'expense') {
        await client.post('/api/finance/expense', { ...form, username });
      } else {
        await client.post('/api/finance/income', form);
      }
      setModal(null);
      setSuccess(modal === 'expense' ? 'Расход добавлен' : 'Доход добавлен');
      setTimeout(() => setSuccess(null), 3000);
      // Обновить баланс
      client.get('/api/finance/balance').then(r => setBalance(r.data.balance)).catch(() => {});
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка при сохранении');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div className="page-title">Финансы</div>
      </div>

      {success && <div className="alert alert-success">{success}</div>}

      {/* Копилка */}
      <div className="card-white" style={{ padding: '20px 16px', marginBottom: 16, textAlign: 'center' }}>
        <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Копилка</div>
        <div style={{ fontSize: 28, fontWeight: 700 }}>{balance ?? '...'}</div>
      </div>

      {/* Кнопки */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <button className="btn btn-secondary" style={{ flex: 1, padding: 14, fontSize: 15 }} onClick={openExpense}>
          − Расход
        </button>
        <button className="btn btn-primary" style={{ flex: 1, padding: 14, fontSize: 15 }} onClick={openIncome}>
          + Доход
        </button>
      </div>

      {/* График */}
      <div className="card-white" style={{ padding: '16px 8px', marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, paddingRight: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, paddingLeft: 8 }}>Статистика</div>
          <div style={{ display: 'flex', gap: 6 }}>
            {['month', 'day'].map(p => (
              <button
                key={p}
                onClick={() => setChartPeriod(p)}
                style={{
                  padding: '4px 10px', fontSize: 12, borderRadius: 8, border: '1px solid #ccc',
                  background: chartPeriod === p ? '#111' : '#fff',
                  color: chartPeriod === p ? '#fff' : '#444',
                  cursor: 'pointer',
                }}
              >
                {p === 'month' ? 'Месяцы' : 'Дни'}
              </button>
            ))}
          </div>
        </div>
        {chartData.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#999', fontSize: 13, padding: '20px 0' }}>Нет данных</div>
        ) : (
          <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData} margin={{ top: 0, right: 8, left: -16, bottom: 0 }}>
                <XAxis dataKey="period" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => v >= 1000 ? `${v/1000}к` : v} />
                <Tooltip
                  formatter={(value, name) => [`${value.toLocaleString('ru')} ₽`, name === 'income' ? 'Доход' : 'Расход']}
                  labelStyle={{ fontSize: 12 }}
                  contentStyle={{ fontSize: 12 }}
                />
                <Legend formatter={name => name === 'income' ? 'Доход' : 'Расход'} wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="income" fill="#111" radius={[3, 3, 0, 0]} />
                <Bar dataKey="expense" fill="#ccc" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartErrorBoundary>
        )}
      </div>

      {/* Модалка */}
      {modal && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-handle" />
            <div className="modal-title">{modal === 'expense' ? 'Новый расход' : 'Новый доход'}</div>

            {error && <div className="alert alert-error">{error}</div>}

            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label">Проект *</label>
                <select className="form-input" value={form.project} onChange={e => set('project', e.target.value)} required>
                  <option value="">Выберите проект</option>
                  {meta.projects.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Сумма *</label>
                <input className="form-input" type="number" value={form.amount} onChange={e => set('amount', e.target.value)} placeholder="5000" required />
              </div>

              <div className="form-group">
                <label className="form-label">{modal === 'expense' ? 'Что? *' : 'За что? *'}</label>
                <input className="form-input" value={form.what} onChange={e => set('what', e.target.value)} placeholder={modal === 'expense' ? 'клининг' : 'билеты 5.04'} required />
              </div>

              {modal === 'expense' && (
                <>
                  <div className="form-group">
                    <label className="form-label">Кто</label>
                    <select className="form-input" value={form.who} onChange={e => set('who', e.target.value)}>
                      <option value="">— выберите —</option>
                      {meta.actors.map(a => <option key={a} value={a}>{a}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Тип траты *</label>
                    <select className="form-input" value={form.expense_type} onChange={e => set('expense_type', e.target.value)} required>
                      <option value="">Выберите тип</option>
                      {meta.expense_types.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Комментарий</label>
                    <input className="form-input" value={form.comment} onChange={e => set('comment', e.target.value)} placeholder="необязательно" />
                  </div>
                </>
              )}

              {modal === 'income' && (
                <div className="form-group">
                  <label className="form-label">Комментарий</label>
                  <input className="form-input" value={form.comment} onChange={e => set('comment', e.target.value)} placeholder="необязательно" />
                </div>
              )}

              <div style={{ fontSize: 12, color: '#999', marginBottom: 12 }}>Дата: сегодня</div>

              <div className="modal-actions">
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? 'Сохранение...' : 'Добавить'}
                </button>
                <button type="button" className="btn btn-secondary" onClick={closeModal}>Отмена</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
