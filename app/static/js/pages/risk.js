import { api } from '../api.js';
import { badge, h, icon, kpi, notice, pageHead, table } from '../ui.js';
import { chartCard, lineConfig, doughnutConfig, groupedBarConfig, COLORS, TYPE_COLOR } from '../charts.js';
import { money, num, pct, fmtDate, ASSET_TYPE_LABEL } from '../format.js';
import { weightBar } from './portfolio.js';

const LEVEL = { ok: ['ok', 'عادی'], watch: ['warn', 'توجه'], warning: ['warn', 'هشدار'], serious: ['bad', 'هشدار جدی'], critical: ['bad', 'بحرانی'], unknown: ['muted', 'نامشخص'] };

export async function render(root) {
  const r = await api.get('/api/risk');
  const dd = r.drawdown, st = r.status, lv = st.levels;
  const [bk, bt] = LEVEL[st.level];
  root.append(pageHead('مرکز مدیریت ریسک', `سقف افت قابل تحمل: ${pct(r.max_drawdown_limit, 0)} از بالاترین ارزش ثبت‌شده`));
  const cur = dd.available ? dd.current_drawdown_pct : 0;
  const max = Number(r.max_drawdown_limit);
  root.append(h('div', { class: `card st-${st.level}` },
    h('div', { class: 'status-big' }, h('span', { class: 'dot' }), h('h2', null, `وضعیت: ${bt}`), badge(dd.available ? `افت فعلی ${pct(cur, 2)}` : 'محاسبه نشد', bk)),
    h('p', { class: 'muted', style: { margin: '6px 0' } }, st.message),
    dd.available ? h('div', null,
      h('div', { class: 'gauge', 'aria-label': 'نوار ریسک' }, h('div', { class: 'needle', style: { left: `${Math.min(100, cur / (max * 1.25) * 100)}%` } })),
      h('div', { class: 'gauge-labels' }, h('span', null, '۰٪'), h('span', null, pct(lv.warning, 0)), h('span', null, pct(lv.serious, 0)), h('span', null, pct(lv.critical, 0)))) : null));
  if (dd.available && !dd.is_current) root.append(notice(`آخرین نقطه ارزش‌گذاری کامل ${fmtDate(dd.last_point_date)} است؛ قیمت معتبر امروز برای همه دارایی‌ها ثبت نشده است.`));
  root.append(h('div', { class: 'grid kpis', style: { marginTop: '14px' } },
    kpi({ label: 'افت فعلی از اوج', value: dd.available ? pct(dd.current_drawdown_pct) : '—', sub: dd.available ? '' : dd.reason, tone: dd.available && cur >= lv.warning ? 'red' : 'green' }),
    kpi({ label: 'درصد ریسک مصرف‌شده', hint: 'افت فعلی نسبت به سقف افت قابل تحمل', value: dd.available ? pct(dd.risk_used_pct, 1) : '—', progress: dd.available ? dd.risk_used_pct : null }),
    kpi({ label: 'بیشترین افت ثبت‌شده', value: dd.available ? pct(dd.max_drawdown_pct) : '—', sub: dd.available ? fmtDate(dd.max_drawdown_date) : '' }),
    kpi({ label: 'تاریخ اوج', value: dd.available ? fmtDate(dd.peak_date) : '—' }),
    kpi({ label: 'کاهش ارزش از اوج (تعدیل‌شده)', hint: 'اختلاف ارزش فعلی با ارزش معادل اوج؛ واریزی‌ها و برداشت‌ها سود/زیان حساب نمی‌شوند.', value: dd.available ? money(dd.loss_from_peak) : '—' }),
  ));
  root.append(h('h2', { class: 'section-title' }, 'هشدارها'));
  root.append(r.alerts.length ? h('div', { class: 'alert-list' }, r.alerts.map((a) => h('div', { class: `alert ${a.level}` }, icon('alert', 18), h('div', null, h('b', null, a.title), a.message))))
    : notice('هشدار فعالی وجود ندارد.', 'ok'));
  root.append(notice(r.disclaimer, 'info'));
  const ex = r.exposure, ct = r.contributions;
  root.append(h('div', { class: 'grid charts' },
    chartCard('افت سرمایه از اوج', () => lineConfig(r.series.filter((p) => p.drawdown_pct !== null), [{ key: 'drawdown_pct', label: 'افت از اوج', color: COLORS.red, fill: 'rgba(255,93,115,.14)' }], { yFmt: 'pct', yReverse: true }), { sub: 'واریزی جدید سود محسوب نمی‌شود' }),
    chartCard('سهم هر دارایی از سبد (وزن)', () => (ex.length ? doughnutConfig(ex.map((e) => ({ name: e.name, value: e.value, asset_type: e.asset_type })), (i) => TYPE_COLOR[i.asset_type] || COLORS.slate) : null)),
  ));
  root.append(h('h2', { class: 'section-title' }, 'سهم دارایی‌ها در ریسک کل'));
  if (!ct.available) root.append(notice(ct.reason, 'info'));
  root.append(h('div', { class: 'card' }, table([
    { label: 'دارایی', render: (x) => x.name },
    { label: 'سهم از ارزش سبد', class: 'num', render: (x) => pct(x.weight_pct, 1) },
    { label: 'سهم آماری از ریسک', class: 'num', render: (x) => (x.risk_share_pct === undefined ? '—' : pct(x.risk_share_pct, 1)) },
    { label: 'نوسان دوره‌ای', class: 'num', render: (x) => (x.volatility_pct === undefined ? '—' : pct(x.volatility_pct, 2)) },
  ], ct.rows, { empty: 'دارایی دارای ارزشی در سبد نیست.' }), ct.available ? h('p', { class: 'sticky-note' }, ct.note) : null));
  root.append(h('h2', { class: 'section-title' }, 'تمرکز و انحراف از ترکیب هدف', h('small', null, `سقف تمرکز: ${pct(r.concentration_limit, 0)}`)));
  root.append(h('div', { class: 'card' }, table([
    { label: 'دارایی', render: (x) => x.name },
    { label: 'وزن فعلی ← هدف', render: (x) => h('div', null, weightBar(x.weight ?? 0, x.target_weight, x.asset_type), h('small', { class: 'muted' }, `${x.weight == null ? '—' : pct(x.weight, 1)} از ${pct(x.target_weight, 1)}`)) },
    { label: 'انحراف', class: 'num', render: (x) => (x.deviation_pp == null ? '—' : `${x.deviation_pp > 0 ? '+' : ''}${num(x.deviation_pp, 1)} واحد درصد`) },
    { label: 'وضعیت', render: (x) => (x.weight != null && x.weight > Number(r.concentration_limit) ? badge('تمرکز بالا', 'bad') : x.deviation_pp != null && Math.abs(x.deviation_pp) >= 10 ? badge('انحراف شدید', 'bad') : x.deviation_pp != null && Math.abs(x.deviation_pp) >= 5 ? badge('انحراف', 'warn') : badge('عادی', 'ok')) },
  ], ex, { empty: 'دارایی دارای ارزشی در سبد نیست.' })));
}
