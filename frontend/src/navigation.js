// Launch parameters select a screen only; API authorization still checks initData.
function getStartParam(tg, search) {
  return tg?.initDataUnsafe?.start_param
    || new URLSearchParams(search).get('tgWebAppStartParam');
}

export function getInitialPlanningMonth(tg, search = window.location.search) {
  const startParam = getStartParam(tg, search);
  const match = /^planning_((?!0000)\d{4}-(?:0[1-9]|1[0-2]))$/.exec(startParam || '');
  return match ? match[1] : '';
}

export function getInitialTab(tg, search = window.location.search) {
  return getStartParam(tg, search) === 'availability' || getInitialPlanningMonth(tg, search)
    ? 'availability' : 'calendar';
}
