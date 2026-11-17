import React, { useState } from 'react';
import MyAvailabilityView from './MyAvailabilityView';
import PlanningView from './PlanningView';

export default function AvailabilityView({ active = true, dataVersion = 0, isAdmin, initialPlanningMonth = '' }) {
  const [planning, setPlanning] = useState(!!initialPlanningMonth);
  const [month, setMonth] = useState(initialPlanningMonth);

  return <>
    <section hidden={planning}>
      <button className="btn btn-secondary availability-planning-link" onClick={() => setPlanning(true)}>
        Планирование составов →
      </button>
      <MyAvailabilityView active={active && !planning} dataVersion={dataVersion}
        initialMonth={initialPlanningMonth} onMonthChange={setMonth} />
    </section>
    {planning && <PlanningView onClose={() => setPlanning(false)} closeLabel="← К моей занятости"
      dataVersion={dataVersion} initialMonth={month} isAdmin={isAdmin} />}
  </>;
}
