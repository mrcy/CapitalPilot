import { api } from '../api.js';
import { badge, h, icon, kpi, notice, pageHead, emptyState } from '../ui.js';
import { fmtDateTime } from '../format.js';
import { currentPortfolio } from '../state.js';
import { chartCard, barConfig, doughnutConfig, groupedBarConfig, lineConfig, COLORS, TYPE_COLOR } from '../charts.js';
import { money, num, pct, signedPct, pnlClass, signedMoney, fmtDate, ASSET_TYPE_LABEL, compact } from '../format.js';
import { openTxForm } from './_txform.js';
import { reload } from '../app.js';

const LEVEL = { ok: ['ok', 'در محدوده عادی'], watch: ['warn', 'توجه'], warning: ['warn', 'هشدار'], serious: ['bad', 'هشدار جدی'], critical: ['bad', 'بحرانی'], unknown: ['muted', 'نامشخص'] };

export async function render(root) {
  const d = await api.get('/api/dashboard');
  const c = d.cards;
  root.append(pageHead('داشبورد مدیریتی', `سبد «${d.portfolio?.name || currentPortfolio()?.name || ''}» — وضعیت سرمایه شما تا ${fmtDate(d.as_of)}`,
    h('button', { class: 'btn primary', onclick: () => openTxForm({ onDone: reload }) }, icon('plus'), 'ثبت تراکنش'),
    h('a', { class: 'btn', href: '#/prices' }, icon('price'), 'ثبت قیمت روز')));
  if (!d.has_data) {
    root.append(emptyState('هنوز تراکنشی ثبت نشده است', 'برنامه هدف شما (سرمایه اولیه و واریزی ماهانه) تنظیم شده است، اما تا وقتی واریزی یا خرید واقعی ثبت نکنید هیچ عددی ساخته نمی‌شود.',
      h('div', { class: 'page-actions', style: { justifyContent: 'center' } }, h('a', { class: 'btn primary', href: '#/contributions' }, 'ثبت واریزی واقعی'), h('button', { class: 'btn', onclick: () => openTxForm({ onDone: reload }) }, 'ثبت تراکنش'))));
  }
  d.warnings.forEach((w) => root.append(notice(w + ' — برای فعال شدن، قیمت معتبر امروز را ثبت کنید.', 'warn')));
  const tr = c.total_return, xr = c.xirr;
  const cash = d.cash_by_platform.filter((p) => Number(p.cash) !== 0).map((p) => `${p.platform}: ${money(p.cash, 0, false)}`).join(' | ');
  root.append(h('div', { class: 'grid kpis' },
    kpi({ label: 'کل سرمایه واریزشده', hint: 'مجموع واریزی‌ها منهای برداشت‌ها', value: money(c.net_invested), sub: 'خالص پس از برداشت', tone: 'accent' }),
    kpi({ label: 'ارزش روز کل سبد', hint: 'دارایی‌های دارای قیمت معتبر + نقدینگی', value: money(c.total_value), sub: d.valuation_complete ? 'همه قیمت‌ها معتبر' : 'ناقص: برخی قیمت‌ها نامعتبر است', tone: d.valuation_complete ? 'accent' : 'gold' }),
    kpi({ label: 'سود و زیان تحقق‌یافته', hint: 'فروش‌ها + سود نقدی − کارمزدها', value: h('span', { class: pnlClass(c.realized_total) }, signedMoney(c.realized_total)), sub: `فروش ${money(c.realized_sales, 0, false)} • سود نقدی ${money(c.dividends, 0, false)} • کارمزد ${money(c.fees, 0, false)}` }),
    kpi({ label: 'سود و زیان تحقق‌نیافته', value: h('span', { class: pnlClass(c.unrealized) }, signedMoney(c.unrealized)), sub: 'ارزش روز − بهای تمام‌شده' }),
    kpi({ label: 'بازدهی کل', hint: 'جمع سود و زیان نسبت به مجموع واریزی‌ها', value: tr.available ? h('span', { class: pnlClass(tr.pct) }, signedPct(tr.pct)) : '—',
      sub: tr.available ? (xr.available ? `XIRR سالانه: ${signedPct(xr.annual_pct)}` : `XIRR: ${xr.reason}`) : tr.reason, tone: tr.available ? (tr.pct >= 0 ? 'green' : 'red') : '' }),
    kpi({ label: 'مجموع واریزی‌ها', value: money(c.deposits), tone: 'green' }),
    kpi({ label: 'مجموع برداشت‌ها', value: money(c.withdrawals), tone: 'red' }),
    kpi({ label: 'میزان نقدینگی', hint: 'نقد واریزشده و هنوز خرج‌نشده در پلتفرم‌ها', value: money(c.cash), sub: cash || 'بدون نقدینگی', valueClass: Number(c.cash) < 0 ? 'neg' : '' }),
    kpi({ label: 'درصد تحقق برنامه', hint: 'مجموع واریزی‌ها نسبت به کل برنامه افق سرمایه‌گذاری', value: c.plan_realization_pct === null ? '—' : pct(c.plan_realization_pct, 1), progress: c.plan_realization_pct, sub: `هدف برنامه: ${money(c.plan_target_total)}` }),
    kpi({ label: 'فاصله تا هدف سرمایه‌گذاری', hint: 'هدف برنامه منهای مجموع واریزی‌ها', value: money(Math.max(0, Number(c.gap_to_target))), sub: Number(c.gap_to_target) < 0 ? `${money(-c.gap_to_target)} بیش از برنامه واریز شده` : `تا ارزش هدف: ${money(c.gap_to_target_value)}`, tone: 'gold' }),
  ));
  // مدیریت دارایی‌ها و وضعیت منابع قیمت
  const mg = d.management, mk = mg.market, pv = mk.providers;
  const enabledNonManual = pv.error + pv.ok;
  const errCard = mk.recent_errors?.length
    ? h('div', { class: 'card', style: { marginTop: '12px' } }, h('b', null, 'آخرین خطاهای دریافت قیمت'),
      h('div', { style: { marginTop: '8px' } }, mk.recent_errors.slice(0, 4).map((e) => h('div', { class: 'log-line bad' },
        h('div', null, h('b', null, e.provider || '—'), e.asset ? ` — ${e.asset}` : ''), h('div', null, e.message), h('div', { class: 't' }, fmtDateTime(e.ts))))))
    : null;
  const kpis = [
    kpi({ label: 'کل دارایی‌ها', value: num(mg.total_assets), sub: mg.archived_assets ? `${num(mg.archived_assets)} بایگانی‌شده` : 'بدون بایگانی', tone: 'accent' }),
    kpi({ label: 'دارایی‌های فعال', value: num(mg.active_assets), tone: 'green' }),
    kpi({ label: 'تعداد پلتفرم‌ها', value: num(mg.platform_count), sub: `${num(mg.portfolio_count)} سبد فعال` }),
    kpi({ label: 'وضعیت منابع قیمت', hint: 'منابع فعال: سالم / دارای خطا', value: `${num(pv.ok)} سالم${pv.error ? ` • ${num(pv.error)} خطا` : ''}`, sub: `${num(pv.enabled)} فعال از ${num(pv.total)} منبع`, tone: pv.error ? 'red' : (pv.ok ? 'green' : 'gold') }),
    kpi({ label: 'قیمت‌های کهنه', hint: 'دارایی‌های فعالی که قیمت معتبر امروز ندارند', value: num(mk.stale_prices + mk.missing_prices), sub: `${num(mk.stale_prices)} کهنه، ${num(mk.missing_prices)} بدون قیمت`, tone: (mk.stale_prices + mk.missing_prices) ? 'gold' : 'green' }),
    kpi({ label: 'آخرین به‌روزرسانی خودکار', value: mk.last_update_at ? fmtDateTime(mk.last_update_at) : '—', sub: `${num(mk.errors_24h)} خطای دریافت در ۲۴ ساعت`, tone: mk.errors_24h ? 'red' : '' }),
  ];
  root.append(h('div', { class: 'market-block' },
    h('h2', { class: 'section-title' }, 'دارایی‌ها و منابع قیمت', h('a', { href: '#/sources', style: { fontSize: '13px', marginRight: 'auto' } }, 'مدیریت منابع ←')),
    h('div', { class: 'grid kpis' }, kpis),
    mk.stale_assets?.length ? notice(`قیمت معتبر ندارند و در ارزش کل لحاظ نشده‌اند: ${mk.stale_assets.join('، ')}`, 'warn') : null,
    errCard));
  // وضعیت ریسک + برنامه
  const [lk, lt] = LEVEL[d.risk.status.level] || LEVEL.unknown;
  root.append(h('div', { class: 'grid cols-2', style: { marginTop: '14px' } },
    h('div', { class: 'card' }, h('div', { class: 'status-big' }, badge(lt, lk), h('b', null, 'مرکز ریسک')), h('p', { class: 'muted' }, d.risk.status.message || d.risk.drawdown.reason || ''),
      h('div', { class: 'alert-list' }, d.risk.alerts.slice(0, 3).map((a) => h('div', { class: `alert ${a.level}` }, icon('alert', 16), h('div', null, h('b', null, a.title), a.message)))),
      h('a', { href: '#/risk' }, 'جزئیات مدیریت ریسک ←')),
    h('div', { class: 'card' }, h('div', { class: 'status-big' }, h('b', null, 'وضعیت واریزی‌ها')),
      h('div', { class: 'kv' },
        h('div', null, h('span', null, 'عقب‌ماندگی تا امروز'), h('b', { class: Number(d.plan.arrears) > 0 ? 'neg' : '' }, money(d.plan.arrears))),
        h('div', null, h('span', null, 'اضافه‌واریزی'), h('b', { class: Number(d.plan.surplus) > 0 ? 'pos' : '' }, money(d.plan.surplus))),
        h('div', null, h('span', null, 'دوره‌های پرداخت‌نشده'), h('b', null, num(d.plan.unpaid_count))),
        h('div', null, h('span', null, 'تحقق برنامه تا امروز'), h('b', null, d.plan.realization_to_date_pct === null ? '—' : pct(d.plan.realization_to_date_pct, 1)))),
      h('a', { href: '#/contributions', style: { display: 'inline-block', marginTop: '10px' } }, 'تقویم واریزی‌ها ←'))));
  // نمودارها
  const ch = d.charts;
  const g = ch.growth.filter((p) => p.complete);
  root.append(h('div', { class: 'grid charts' },
    chartCard('رشد ارزش کل سبد', () => lineConfig(g, [{ key: 'value', label: 'ارزش سبد', color: COLORS.indigo, fill: 'rgba(111,134,255,.14)' }]), { sub: 'فقط نقاط با قیمت معتبر' }),
    chartCard('سرمایه واریزشده در برابر ارزش روز', () => lineConfig(ch.capital_vs_value, [
      { key: 'net_invested', label: 'سرمایه خالص واریزشده', color: COLORS.slate, stepped: true }, { key: 'value', label: 'ارزش روز سبد', color: COLORS.green }])),
    chartCard('ترکیب دارایی‌ها', () => doughnutConfig(ch.allocation, (i) => TYPE_COLOR[i.asset_type] || COLORS.slate)),
    chartCard('بازدهی هر دارایی', () => barConfig(ch.asset_returns.map((a) => a.name), ch.asset_returns.map((a) => a.return_pct), { fmt: 'pct' }), { sub: 'نسبت به مجموع مبلغ خرید' }),
    chartCard('عملکرد ماهانه', () => barConfig(ch.monthly.map((m) => m.label), ch.monthly.map((m) => m.return_pct), { fmt: 'pct' }), { sub: 'بازده زمانی (بدون اثر واریزی)' }),
    chartCard('افت سرمایه (Drawdown)', () => lineConfig(ch.drawdown, [{ key: 'drawdown_pct', label: 'افت از اوج', color: COLORS.red, fill: 'rgba(255,93,115,.14)' }], { yFmt: 'pct', yReverse: true }), { sub: 'بر مبنای بازده تعدیل‌شده با جریان نقدی' }),
  ));
}
