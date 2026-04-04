import React, { useState, useEffect } from 'react';
import client from '../api/client';

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

  useEffect(() => {
    client.get('/api/finance/balance').then(r => setBalance(r.data.balance)).catch(() => {});
    client.get('/api/finance/meta').then(r => setMeta(r.data)).catch(() => {});
  }, []);

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
