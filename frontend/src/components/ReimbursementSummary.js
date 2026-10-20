import React, { useEffect, useRef, useState } from 'react';
import client from '../api/client';
import './ReimbursementSummary.css';

const money = value => `${value.toLocaleString('ru-RU')} ₽`;
const dateLabel = value => value ? value.split('-').reverse().join('.') : 'Без даты';
const nameKey = value => value.trim().replace(/\s+/g, ' ').toLocaleLowerCase('ru');

function UnassignedNotice({ data, label }) {
  if (!data.personal && !data.returned) return null;
  return (
    <div role="status" className="alert alert-error">
      {label}: есть операции без имени — личные траты {money(data.personal)},
      {' '}возвраты {money(data.returned)}. Итог предварительный:
      уточните имена в таблице. Возвраты без получателя не вычтены.
    </div>
  );
}

function PersonHistory({ who, onClose }) {
  const [transactions, setTransactions] = useState(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const closeRef = useRef(null);
  useEffect(() => {
    const previousFocus = document.activeElement;
    closeRef.current?.focus();
    const onKey = event => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previousFocus?.focus();
    };
  }, [onClose]);
  useEffect(() => {
    const controller = new AbortController();
    setTransactions(null);
    setError(false);
    client.get('/api/finance/reimbursements/history', {
      params: { who }, signal: controller.signal,
    }).then(({ data }) => {
      if (!controller.signal.aborted) setTransactions(data.transactions);
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    });
    return () => controller.abort();
  }, [who, retry]);
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal reimbursement-history" role="dialog" aria-modal="true"
        aria-labelledby="reimbursement-person" onClick={event => event.stopPropagation()}>
        <div className="modal-handle" />
        <div className="modal-title" id="reimbursement-person">{who}</div>
        <p className="reimbursement-note">Личные траты и возвраты за всё время · сначала новые</p>
        {error ? (
          <div role="alert">Не удалось загрузить историю. <button onClick={() => setRetry(v => v + 1)}>Повторить</button></div>
        ) : !transactions ? (
          <div role="status">Загрузка…</div>
        ) : transactions.length === 0 ? (
          <p>Личных трат и возвратов пока нет</p>
        ) : (
          <ul className="reimbursement-history-list">
            {transactions.map(tx => {
              const returned = tx.expense_type === 'Возврат';
              return (
                <li key={tx.id}>
                  <div className="reimbursement-history-heading">
                    <span>{returned ? 'Возврат' : 'Личная трата'}</span>
                    <strong className={returned ? 'reimbursement-refund' : ''}>
                      {returned ? '−' : '+'}{money(tx.amount)}
                    </strong>
                  </div>
                  <div>{tx.what}</div>
                  <div className="reimbursement-note">{dateLabel(tx.date)}{tx.project ? ` · ${tx.project}` : ''}</div>
                  {tx.comment && <div className="reimbursement-note">{tx.comment}</div>}
                </li>
              );
            })}
          </ul>
        )}
        <div className="modal-actions">
          <button ref={closeRef} className="btn btn-secondary" onClick={onClose}>Закрыть</button>
        </div>
      </div>
    </div>
  );
}

export default function ReimbursementSummary({ data, loading }) {
  const [person, setPerson] = useState(null);
  const closeHistory = React.useCallback(() => setPerson(null), []);
  // Keep people present in either period; the recent figure is a period balance,
  // not an allocation of old refunds to individual purchases.
  const people = new Map();
  (data?.people || []).forEach(row => people.set(nameKey(row.who), { ...row, recent: 0 }));
  (data?.recent?.people || []).forEach(row => {
    const key = nameKey(row.who);
    people.set(key, { ...(people.get(key) || { who: row.who, amount: 0 }), recent: row.amount });
  });
  const rows = [...people.values()].sort((a, b) => b.amount - a.amount || b.recent - a.recent || a.who.localeCompare(b.who, 'ru'));
  return (
    <div className="card-white reimbursement-summary">
      <div className="reimbursement-note reimbursement-center">Всего к возврату</div>
      {!data ? (
        <div role="status" className="reimbursement-center">
          {loading ? 'Загрузка…' : 'Не удалось загрузить суммы к возврату'}
        </div>
      ) : (
        <>
          <div className="reimbursement-totals">
            <div><span>За всё время</span><strong>{money(data.total)}</strong></div>
            <div><span>За 30 дней</span><strong>{data.recent ? money(data.recent.total) : '—'}</strong></div>
          </div>
          <p className="reimbursement-note reimbursement-center">
            Личные траты минус возвраты за тот же период.
            {data.recent && <> Последние 30 дней: {dateLabel(data.recent.from_date)}–{dateLabel(data.recent.to_date)}.</>}
            {' '}Возвраты могут относиться к более ранним тратам; отрицательный остаток показан как 0.
          </p>
          <UnassignedNotice data={data.unassigned} label="За всё время" />
          {data.recent && <UnassignedNotice data={data.recent.unassigned} label="За 30 дней" />}
          {rows.length > 0 && (
            <>
              <table className="reimbursement-table">
                <thead><tr>
                  <th scope="col" aria-label="Имя" />
                  <th scope="col">Всё время</th>
                  <th scope="col">30 дней</th>
                </tr></thead>
                <tbody>{rows.map(row => (
                  <tr key={nameKey(row.who)}>
                    <td><button title={row.who} onClick={() => setPerson(row.who)}>{row.who}</button></td>
                    <td>{money(row.amount)}</td>
                    <td>{data.recent ? money(row.recent) : '—'}</td>
                  </tr>
                ))}</tbody>
              </table>
              <p className="reimbursement-note">Нажмите на имя, чтобы посмотреть траты и возвраты.</p>
            </>
          )}
          {data.unassigned.personal > 0 && <div>Без имени: {money(data.unassigned.personal)}</div>}
          {data.total === 0 && data.unassigned.returned === 0 && (
            <div className="reimbursement-note reimbursement-center">Все личные траты компенсированы</div>
          )}
        </>
      )}
      {person && <PersonHistory key={person} who={person} onClose={closeHistory} />}
    </div>
  );
}
