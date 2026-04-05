import React, { useState, useEffect } from 'react';
import client from '../api/client';

function smoothPath(points) {
  if (points.length === 0) return '';
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(points.length - 1, i + 2)];
    const cp1x = p1.x + (p2.x - p0.x) / 6;
    const cp1y = p1.y + (p2.y - p0.y) / 6;
    const cp2x = p2.x - (p3.x - p1.x) / 6;
    const cp2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${p2.x} ${p2.y}`;
  }
  return d;
}

function SplineChart({ data }) {
  const [tooltip, setTooltip] = useState(null);
  const h = 180, padL = 44, padB = 28, padT = 16, padR = 8;
  const totalW = window.innerWidth - 32;
  const spacing = (totalW - padL - padR) / Math.max(data.length - 1, 1);
  const chartH = h - padT - padB;

  let cum = 0;
  const cumValues = data.map(d => { cum += d.income - d.expense; return cum; });

  const posMax = Math.max(...cumValues, 0);
  const negMin = Math.min(...cumValues, 0);
  const range = Math.max(posMax - negMin, 1);
  // небольшой отступ сверху/снизу
  const yTop = posMax + range * 0.08;
  const yBot = negMin - range * 0.08;
  const totalRange = yTop - yBot;

  const toY = v => padT + (yTop - v) / totalRange * chartH;
  const zeroY = toY(0);

  const pts = cumValues.map((v, i) => ({ x: padL + i * spacing, y: toY(v) }));
  const areaPath = `${smoothPath(pts)} L ${pts[pts.length-1].x} ${zeroY} L ${pts[0].x} ${zeroY} Z`;

  const labelStep = Math.max(1, Math.ceil(data.length / 7));
  const fmtK = v => {
    if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(0)}к`;
    return v.toFixed(0);
  };

  // Y-axis labels: top, zero (if in range), bottom
  const gridVals = [yTop, 0, yBot].filter(v => v >= yBot && v <= yTop);

  return (
    <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
      <div style={{ position: 'relative', display: 'inline-block' }}>
        {tooltip && (
          <div style={{
            position: 'absolute', top: 0,
            left: tooltip.x > totalW * 0.7 ? 'auto' : Math.max(0, tooltip.x - 64),
            right: tooltip.x > totalW * 0.7 ? (totalW - tooltip.x - 10) : 'auto',
            background: '#111', color: '#fff', borderRadius: 6, padding: '4px 8px',
            fontSize: 11, pointerEvents: 'none', whiteSpace: 'nowrap', zIndex: 10,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{tooltip.period}</div>
            <div>Баланс: {tooltip.cum >= 0 ? '+' : ''}{Math.round(tooltip.cum).toLocaleString('ru')} ₽</div>
            <div style={{ color: '#aaa', marginTop: 2 }}>
              +{tooltip.income.toLocaleString('ru')} / −{tooltip.expense.toLocaleString('ru')}
            </div>
          </div>
        )}
        <svg width={totalW} height={h}>
          {/* Grid */}
          {gridVals.map(v => (
            <g key={v}>
              <line x1={padL} x2={totalW - padR} y1={toY(v)} y2={toY(v)}
                stroke={v === 0 ? '#ccc' : '#eee'} strokeWidth={v === 0 ? 1 : 1} />
              <text x={padL - 4} y={toY(v) + 4} textAnchor="end" fontSize={9} fill={v === 0 ? '#aaa' : '#bbb'}>
                {fmtK(v)}
              </text>
            </g>
          ))}
          {/* Area fill */}
          <path d={areaPath} fill="#111" fillOpacity={0.07} />
          {/* Line */}
          <path d={smoothPath(pts)} fill="none" stroke="#111" strokeWidth={1.5} />
          {/* Tooltip crosshair */}
          {tooltip && (
            <line x1={tooltip.x} x2={tooltip.x} y1={padT} y2={padT + chartH}
              stroke="#ccc" strokeWidth={1} strokeDasharray="3,3" />
          )}
          {/* Hit areas + date labels */}
          {data.map((d, i) => (
            <g key={d.period}
              onMouseEnter={() => setTooltip({ ...d, x: pts[i].x, cum: cumValues[i] })}
              onMouseLeave={() => setTooltip(null)}
              onTouchStart={() => setTooltip({ ...d, x: pts[i].x, cum: cumValues[i] })}
              onTouchEnd={() => setTimeout(() => setTooltip(null), 1500)}
              style={{ cursor: 'pointer' }}
            >
              <rect x={pts[i].x - spacing / 2} y={padT} width={spacing} height={chartH} fill="transparent" />
              {i % labelStep === 0 && (
                <text x={pts[i].x} y={h - 6} textAnchor="middle" fontSize={9} fill="#999">
                  {d.period.slice(0, 5)}
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>
      <div style={{ paddingLeft: padL, marginTop: 4, fontSize: 11, color: '#888' }}>
        Накопительный баланс
      </div>
    </div>
  );
}

function SimpleBarChart({ data }) {
  const [tooltip, setTooltip] = useState(null);
  const h = 160, padL = 36, padB = 28, padT = 8, padR = 8;
  const totalW = window.innerWidth - 32;
  const max = Math.max(...data.map(d => Math.max(
    d.income,
    (d.expense_foshu || 0) + (d.expense_personal || 0) + (d.expense_donation || 0)
  )), 1);
  const innerW = totalW - padL - padR;
  const groupW = innerW / data.length;
  const barW = Math.max(3, Math.min(12, Math.floor(groupW * 0.35)));
  const gap = Math.max(1, Math.floor(groupW * 0.1));
  const chartH = h - padT - padB;
  const bottom = padT + chartH;

  return (
    <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
      <div style={{ position: 'relative', display: 'inline-block' }}>
        {tooltip && (
          <div style={{
            position: 'absolute', top: 0,
            left: tooltip.x > totalW * 0.7 ? 'auto' : Math.max(0, tooltip.x - 70),
            right: tooltip.x > totalW * 0.7 ? (totalW - tooltip.x - 10) : 'auto',
            background: '#111', color: '#fff', borderRadius: 6, padding: '4px 8px',
            fontSize: 11, pointerEvents: 'none', whiteSpace: 'nowrap', zIndex: 10,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{tooltip.period}</div>
            <div>Доход: {(tooltip.income || 0).toLocaleString('ru')} ₽</div>
            {(tooltip.expense_foshu || 0) > 0 && <div>ФоШу: {tooltip.expense_foshu.toLocaleString('ru')} ₽</div>}
            {(tooltip.expense_personal || 0) > 0 && <div>Личные: {tooltip.expense_personal.toLocaleString('ru')} ₽</div>}
            {(tooltip.expense_donation || 0) > 0 && <div>Пожертв.: {tooltip.expense_donation.toLocaleString('ru')} ₽</div>}
          </div>
        )}
        <svg width={totalW} height={h}>
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
          {data.map((d, i) => {
            const foshu = d.expense_foshu || 0;
            const personal = d.expense_personal || 0;
            const donation = d.expense_donation || 0;
            const x = padL + i * groupW;
            const ih = Math.max(2, (d.income / max) * chartH);
            const fH = (foshu / max) * chartH;
            const pH = (personal / max) * chartH;
            const dH = (donation / max) * chartH;
            return (
              <g key={d.period}
                onMouseEnter={() => setTooltip({ ...d, x: x + groupW / 2 })}
                onMouseLeave={() => setTooltip(null)}
                onTouchStart={() => setTooltip({ ...d, x: x + groupW / 2 })}
                onTouchEnd={() => setTimeout(() => setTooltip(null), 1500)}
                style={{ cursor: 'pointer' }}
              >
                <rect x={x} y={bottom - ih} width={barW} height={ih} fill="#111" rx={2} />
                {donation > 0 && <rect x={x + barW + gap} y={bottom - fH - pH - dH} width={barW} height={Math.max(1, dH)} fill="#ddd" rx={2} />}
                {personal > 0 && <rect x={x + barW + gap} y={bottom - fH - pH} width={barW} height={Math.max(1, pH)} fill="#e57373" rx={donation > 0 ? 0 : 2} />}
                {foshu > 0 && <rect x={x + barW + gap} y={bottom - fH} width={barW} height={Math.max(1, fH)} fill="#8B0000" rx={personal > 0 || donation > 0 ? 0 : 2} />}
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
      <div style={{ display: 'flex', gap: 10, paddingLeft: padL, marginTop: 4, flexWrap: 'wrap' }}>
        {[['#111', 'Доход'], ['#8B0000', 'ФоШу'], ['#e57373', 'Личные'], ['#ddd', 'Пожертвования']].map(([c, label]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#666' }}>
            <div style={{ width: 10, height: 10, background: c, borderRadius: 2, border: c === '#ddd' ? '1px solid #bbb' : 'none' }} /> {label}
          </div>
        ))}
      </div>
    </div>
  );
}

const todayISO = () => new Date().toISOString().slice(0, 10);
const isoToDMY = iso => { const [y, m, d] = iso.split('-'); return `${d}.${m}.${y}`; };

const EMPTY_EXPENSE = { project: '', amount: '', what: '', expense_type: '', comment: '', who: '', date: todayISO() };
const EMPTY_INCOME  = { project: '', amount: '', what: '', comment: '', date: todayISO() };

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
  const [fromDate, setFromDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [transactions, setTransactions] = useState([]);

  const loadTransactions = () => {
    client.get('/api/finance/transactions').then(r => setTransactions(r.data.transactions)).catch(() => {});
  };

  useEffect(() => {
    client.get('/api/finance/balance').then(r => setBalance(r.data.balance)).catch(() => {});
    client.get('/api/finance/meta').then(r => setMeta(r.data)).catch(() => {});
    loadTransactions();
  }, []);

  useEffect(() => {
    const [y, m, d] = fromDate.split('-');
    const params = { period: chartPeriod, from_date: `${d}.${m}.${y}` };
    client.get('/api/finance/chart', { params })
      .then(r => setChartData(r.data.data))
      .catch(() => {});
  }, [chartPeriod, fromDate]);

  const deleteTransaction = async (type, id) => {
    if (!window.confirm('Удалить операцию из БД и таблицы?')) return;
    try {
      await client.delete(`/api/finance/transactions/${type}/${id}`);
      loadTransactions();
      client.get('/api/finance/balance').then(r => setBalance(r.data.balance)).catch(() => {});
    } catch (e) {
      alert('Ошибка при удалении');
    }
  };

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
      const payload = { ...form, date: isoToDMY(form.date) };
      if (modal === 'expense') {
        await client.post('/api/finance/expense', { ...payload, username });
      } else {
        await client.post('/api/finance/income', payload);
      }
      setModal(null);
      setSuccess(modal === 'expense' ? 'Расход добавлен' : 'Доход добавлен');
      setTimeout(() => setSuccess(null), 3000);
      client.get('/api/finance/balance').then(r => setBalance(r.data.balance)).catch(() => {});
      loadTransactions();
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
        {meta.sheets_url && (
          <a
            href={meta.sheets_url}
            target="_blank"
            rel="noreferrer"
            className="btn btn-secondary"
            style={{ fontSize: 13, padding: '6px 10px', textDecoration: 'none' }}
          >
            📊 Таблица
          </a>
        )}
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, paddingRight: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, paddingLeft: 8 }}>Статистика</div>
          <div style={{ display: 'flex', gap: 6 }}>
            {['month', 'day'].map(p => (
              <button key={p} onClick={() => setChartPeriod(p)} style={{
                padding: '4px 10px', fontSize: 12, borderRadius: 8, border: '1px solid #ccc',
                background: chartPeriod === p ? '#111' : '#fff',
                color: chartPeriod === p ? '#fff' : '#444', cursor: 'pointer',
              }}>
                {p === 'month' ? 'Месяцы' : 'История'}
              </button>
            ))}
          </div>
        </div>
        {chartPeriod === 'month' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: '#888' }}>С:</span>
            <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
              style={{ fontSize: 12, border: '1px solid #ddd', borderRadius: 6, padding: '3px 6px', outline: 'none' }} />
          </div>
        )}
        {chartData.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#999', fontSize: 13, padding: '20px 0' }}>Нет данных</div>
        ) : chartPeriod === 'day' ? (
          <SplineChart data={chartData} />
        ) : (
          <SimpleBarChart data={chartData} />
        )}
      </div>

      {/* Последние операции */}
      {transactions.length > 0 && (
        <div className="card-white" style={{ padding: '12px 0', marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, padding: '0 16px', marginBottom: 8 }}>Последние операции</div>
          {transactions.map(tx => (
            <div key={`${tx.type}-${tx.id}`} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '8px 16px', borderBottom: '1px solid #f0f0f0',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                background: tx.type === 'income' ? '#111' : '#eee',
                color: tx.type === 'income' ? '#fff' : '#444',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 15, fontWeight: 700,
              }}>
                {tx.type === 'income' ? '+' : '−'}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {tx.what}
                </div>
                <div style={{ fontSize: 11, color: '#999' }}>{tx.date} · {tx.project}</div>
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, flexShrink: 0 }}>
                {tx.type === 'income' ? '+' : '−'}{(() => {
                  const n = parseFloat(String(tx.amount).replace('р.', '').replace(/\s/g, '').replace(',', '.'));
                  return isNaN(n) ? tx.amount : n.toLocaleString('ru', { maximumFractionDigits: 0 });
                })()}
              </div>
              <button
                onClick={() => deleteTransaction(tx.type, tx.id)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ccc', fontSize: 18, padding: '0 0 0 4px', flexShrink: 0 }}
              >×</button>
            </div>
          ))}
        </div>
      )}

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

              <div className="form-group">
                <label className="form-label">Дата</label>
                <input className="form-input" type="date" value={form.date} onChange={e => set('date', e.target.value)} required />
              </div>

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
