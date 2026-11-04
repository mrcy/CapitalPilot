import { api } from '../api.js';
import { badge, h, kpi, notice, pageHead, table, typeDot } from '../ui.js';
import { chartCard, barConfig, doughnutConfig, groupedBarConfig, COLORS, TYPE_COLOR } from '../charts.js';
import { money, num, pct, signedPct, signedMoney, pnlClass, units, ASSET_TYPE_LABEL, REASON_LABEL, fmtDateTime } from '../format.js';

export const weightBar = (w, target, type) => h('div', { class: `wbar t-${type}-bar`, title: `وزن فعلی ${pct(w)} | هدف ${pct(target)}` },
  h('span', { style: { width: `${Math.min(100, Number(w) || 0)}%` } }), h('i', { style: { right: `${Math.min(100, Number(target) || 0)}%` } }));

export async function render(root) {
  const p = await api.get('/api/portfolio');
  const t = p.totals;
  root.append(pageHead('سبد سرمایه‌گذاری', 'ترکیب فعلی در برابر ترکیب هدف، به تفکیک دارایی و پلتفرم'));
  p.warnings.forEach((w) => root.append(notice(`${w} — ارزش این دارایی‌ها در جمع لحاظ نشده است.`)));
  root.append(notice(p.emergency_fund_note, 'info'));
  if (Math.abs(Number(p.target_sum) - 100) > 0.0001) root.append(notice(`مجموع وزن‌های هدف ${num(p.target_sum, 2)}٪ است و ۱۰۰٪ نیست؛ از تنظیمات اصلاح کنید.`));
  root.append(h('div', { class: 'grid kpis' },
    kpi({ label: 'ارزش کل سبد', value: money(t.total_value), sub: `دارایی‌ها ${money(t.assets_value, 0, false)} + نقدینگی ${money(t.cash, 0, false)}`, tone: 'accent' }),
    kpi({ label: 'بهای تمام‌شده دارایی‌ها', value: money(t.cost_basis) }),
    kpi({ label: 'سود/زیان تحقق‌نیافته', value: h('span', { class: pnlClass(t.unrealized) }, signedMoney(t.unrealized)) }),
    kpi({ label: 'سود/زیان تحقق‌یافته', value: h('span', { class: pnlClass(t.realized_total) }, signedMoney(t.realized_total)) }),
    kpi({ label: 'بازدهی کل', value: p.total_return.available ? h('span', { class: pnlClass(p.total_return.pct) }, signedPct(p.total_return.pct)) : '—', sub: p.total_return.available ? 'نسبت به مجموع واریزی‌ها' : p.total_return.reason }),
  ));
  root.append(h('h2', { class: 'section-title' }, 'دارایی‌ها'));
  root.append(h('div', { class: 'card' }, table([
    { label: 'دارایی', render: (a) => h('a', { href: `#/assets/${a.id}` }, typeDot(a.asset_type), a.name, a.active ? '' : badge('غیرفعال')) },
    { label: 'پلتفرم', render: (a) => a.platform },
    { label: 'ارزش روز', class: 'num', render: (a) => (a.value === null ? badge(REASON_LABEL[a.quote.reason] || 'بدون قیمت', 'warn') : money(a.value)) },
    { label: 'سود/زیان', class: 'num', render: (a) => (a.unrealized === null ? '—' : h('span', { class: pnlClass(a.unrealized) }, `${signedMoney(a.unrealized)} (${signedPct(a.unrealized_pct)})`)) },
    { label: 'وزن فعلی / هدف', render: (a) => h('div', null, weightBar(a.weight ?? 0, a.target_weight, a.asset_type), h('small', { class: 'muted' }, `${a.weight === null ? '—' : pct(a.weight, 1)} از ${pct(a.target_weight, 1)}`)) },
    { label: 'اختلاف', class: 'num', render: (a) => (a.deviation_pp === null ? '—' : h('b', { class: Math.abs(a.deviation_pp) >= 5 ? 'neg' : (a.deviation_pp > 0 ? '' : '') }, `${a.deviation_pp > 0 ? '+' : ''}${num(a.deviation_pp, 1)}`)) },
  ], p.assets.filter((a) => a.active || Number(a.units) > 0), { empty: 'دارایی فعالی وجود ندارد.' })));
  root.append(h('h2', { class: 'section-title' }, 'پلتفرم‌ها'));
  root.append(h('div', { class: 'card' }, table([
    { label: 'پلتفرم', render: (r) => r.platform },
    { label: 'ارزش دارایی‌ها', class: 'num', render: (r) => money(r.assets_value) },
    { label: 'نقدینگی', class: 'num', render: (r) => money(r.cash) },
    { label: 'واریزی‌ها', class: 'num', render: (r) => money(r.deposits) },
    { label: 'سود/زیان کل', class: 'num', render: (r) => (r.total_pnl === null ? '—' : h('span', { class: pnlClass(r.total_pnl) }, `${signedMoney(r.total_pnl)} ${r.return_pct === null ? '' : `(${signedPct(r.return_pct)})`}`)) },
    { label: 'وزن فعلی / هدف', class: 'num', render: (r) => `${r.weight === null ? '—' : pct(r.weight, 1)} / ${pct(r.target_weight, 1)}` },
  ], p.platforms)));
  const act = p.assets.filter((a) => a.active);
  root.append(h('div', { class: 'grid charts' },
    chartCard('وزن فعلی در برابر وزن هدف', () => (p.valuation_complete && Number(t.assets_value) > 0 ? groupedBarConfig(act.map((a) => a.name),
      [{ label: 'فعلی', data: act.map((a) => a.weight ?? 0), color: COLORS.indigo }, { label: 'هدف', data: act.map((a) => a.target_weight), color: '#ffffff40' }], { fmt: 'pct' }) : null), { sub: 'درصد' }),
    chartCard('ترکیب بر اساس نوع دارایی', () => doughnutConfig(p.types.map((x) => ({ name: ASSET_TYPE_LABEL[x.type] || x.type, value: x.value, asset_type: x.type })), (i) => TYPE_COLOR[i.asset_type] || COLORS.slate)),
  ));
  if (p.fx.length) {
    root.append(h('h2', { class: 'section-title' }, 'اثر نرخ ارز', h('small', null, 'تفکیک سود/زیان تحقق‌نیافته دارایی‌های ارزی')));
    root.append(h('div', { class: 'card' }, table([
      { label: 'دارایی', render: (r) => r.name },
      { label: 'نرخ میانگین خرید', class: 'num', render: (r) => (r.available ? money(r.fx_rate_avg_cost, 0, false) : '—') },
      { label: 'نرخ فعلی', class: 'num', render: (r) => (r.available ? money(r.fx_rate_now, 0, false) : '—') },
      { label: 'اثر قیمت دارایی', class: 'num', render: (r) => (r.available ? h('span', { class: pnlClass(r.asset_price_effect) }, signedMoney(r.asset_price_effect)) : '—') },
      { label: 'اثر تغییر نرخ ارز', class: 'num', render: (r) => (r.available ? h('span', { class: pnlClass(r.fx_rate_effect) }, signedMoney(r.fx_rate_effect)) : h('small', { class: 'muted' }, r.reason)) },
    ], p.fx)));
  }
}
