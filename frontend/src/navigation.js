// Launch parameters select a screen only; API authorization still checks initData.
export function getInitialPlanningMonth(tg, search = window.location.search) {
  const startParam = tg?.initDataUnsafe?.start_param
    || new URLSearchParams(search).get('tgWebAppStartParam');
  const match = /^planning_((?!0000)\d{4}-(?:0[1-9]|1[0-2]))$/.exec(startParam || '');
  return match ? match[1] : '';
}
