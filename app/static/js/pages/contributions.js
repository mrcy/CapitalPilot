import { api } from '../api.js';
import { reload } from '../app.js';
import { badge, clear, formModal, h, icon, kpi, notice, pageHead, table, toast, toastWarnings } from '../ui.js';
import { chartCard, groupedBarConfig, COLORS } from '../charts.js';
import { money, num, pct, fmtDate, STATUS_LABEL, signedMoney, pnlClass } from '../format.js';

const KIND = { paid: 'ok', extra: 'ok', partial: 'warn', partial_overdue: 'bad', overdue: 'bad', due: 'gold', upcoming: 'muted' };

function recordForm(period, plan, onDone) {
  const remaining = Math.max(0, Number(period.planned) - Number(period.actual));
  const targets = plan.platform_targets;
  const split = (amount) => {
    const tw = targets.reduce((s, t) => s + Number(t.weight), 0) || 1;
    const out = {}; let used = 0;
    targets.forEach((t, i) => { out[t.platform_id] = i === targets.length - 1 ? amount - used : Math.round(amount * Number(t.weight) / tw); used += out[t.platform_id] || 0; });
    return out;
  };
  const init = split(remaining || Number(period.planned));
  const fields = [
    { name: 'date', label: 'تاریخ پرداخت', type: 'date', required: true },
    { name: 'amount', label: 'مبلغ کل واریزی (تومان)', type: 'decimal', required: true, hint: 'با تغییر مبلغ، تقسیم بین پلتفرم‌ها بر اساس ترکیب هدف به‌روز می‌شود.' },
    ...targets.map((t) => ({ name: `p_${t.platform_id}`, label: `سهم ${t.platform} (تومان)`, type: 'decimal' })),
    { name: 'note', label: 'توضیحات', type: 'text', wide: true },
  ];
  const values = { amount: remaining || Number(period.planned), note: '' };
  targets.forEach((t) => { values[`p_${t.platform_id}`] = init[t.platform_id]; });
  let lock = false;
  const f = formModal({
    title: `ثبت واریزی واقعی — ${period.seq === 0 ? 'سرمایه اولیه' : `ماه ${num(period.seq)}`} (${period.label})`, fields, values, submitLabel: 'ثبت واریزی',
    extra: notice(`برنامه این دوره ${money(period.planned)} و واریزشده تا اکنون ${money(period.actual)} است. برای هر پلتفرم یک تراکنش «واریز سرمایه» ثبت می‌شود.`, 'info'),
    onChange: (x, api2) => {
      if (lock) return;
    },
    onSubmit: async (x, m) => {
      const allocations = {};
      let sum = 0;
      targets.forEach((t) => { const v = Number(x[`p_${t.platform_id}`] || 0); if (v > 0) { allocations[t.platform_id] = String(x[`p_${t.platform_id}`]); sum += v; } });
      const body = { date: x.date, note: x.note || '' };
      if (sum > 0) body.allocations = allocations; else body.amount = x.amount;
      const res = await api.post(`/api/contributions/${period.seq}/record`, body);
      m.close(); toast('واریزی ثبت شد.', 'success'); toastWarnings(res.warnings); onDone();
    },
  });
  // تقسیم خودکار هنگام تغییر مبلغ کل
  const amt = f.refs.amount;
  amt.addEventListener('input', () => {
    const a = Number(f.getValues().amount);
    if (!Number.isFinite(a) || a <= 0) return;
    const s = split(a);
    targets.forEach((t) => { f.refs[`p_${t.platform_id}`].value = String(s[t.platform_id]); });
  });
  return f;
}

function editPeriod(period, onDone) {
  return formModal({
    title: `ویرایش مبلغ برنامه‌ریزی‌شده — ${period.label}`, submitLabel: 'ذخیره',
    fields: [{ name: 'planned_amount', label: 'مبلغ برنامه‌ریزی‌شده (تومان)', type: 'decimal', required: true }, { name: 'due_date', label: 'سررسید', type: 'date', required: true }, { name: 'note', label: 'توضیحات', type: 'text', wide: true }],
    values: { planned_amount: period.planned, due_date: period.due_date, note: '' },
    onSubmit: async (x, m) => { await api.patch(`/api/contributions/${period.seq}`, { planned_amount: x.planned_amount, due_date: x.due_date }); m.close(); toast('ذخیره شد.', 'success'); onDone(); },
  });
}

export async function render(root) {
  const plan = await api.get('/api/contributions');
  root.append(pageHead('واریزی‌های ماهانه', `برنامه: سرمایه اولیه ${money(plan.initial_capital)} و ${money(plan.monthly_contribution)} در هر ماه`,
    h('a', { class: 'btn', href: '#/settings' }, icon('settings'), 'تغییر برنامه')));
  if (plan.unpaid_count) root.append(notice(`${num(plan.unpaid_count)} دوره سررسیدشده پرداخت کامل نشده است؛ مجموع عقب‌ماندگی ${money(plan.arrears)}.`));
  root.append(h('div', { class: 'grid kpis' },
    kpi({ label: 'کل برنامه افق', value: money(plan.target_total), tone: 'accent' }),
    kpi({ label: 'مجموع واریزی واقعی', value: money(plan.total_deposits), tone: 'green', sub: Number(plan.unlinked_deposits) ? `${money(plan.unlinked_deposits, 0, false)} خارج از برنامه` : '' }),
    kpi({ label: 'درصد تحقق برنامه', value: plan.realization_pct === null ? '—' : pct(plan.realization_pct, 1), progress: plan.realization_pct }),
    kpi({ label: 'عقب‌ماندگی (سررسیدشده)', value: money(plan.arrears), tone: Number(plan.arrears) > 0 ? 'red' : '', valueClass: Number(plan.arrears) > 0 ? 'neg' : '' }),
    kpi({ label: 'اضافه‌واریزی', value: money(plan.surplus), tone: Number(plan.surplus) > 0 ? 'green' : '' }),
  ));
  root.append(h('h2', { class: 'section-title' }, 'تقویم واریزی‌ها', h('small', null, 'برنامه‌ریزی‌شده در برابر واقعی')));
  root.append(h('div', { class: 'plan-grid' }, plan.periods.map((p) => h('div', { class: `period s-${p.status}` },
    h('div', { class: 'top' }, h('b', null, p.seq === 0 ? 'سرمایه اولیه' : `ماه ${num(p.seq)}`), badge(STATUS_LABEL[p.status], KIND[p.status])),
    h('small', { class: 'muted' }, `سررسید: ${fmtDate(p.due_date)}${p.paid_dates.length ? ` • پرداخت: ${p.paid_dates.map((d) => fmtDate(d)).join('، ')}` : ''}`),
    h('div', { class: 'amt' }, h('span', null, 'برنامه'), h('b', null, money(p.planned, 0, false))),
    h('div', { class: 'amt' }, h('span', null, 'واقعی'), h('b', null, money(p.actual, 0, false))),
    h('div', { class: 'amt' }, h('span', null, Number(p.diff) >= 0 ? 'اضافه' : 'عقب‌ماندگی'), h('b', { class: Number(p.diff) >= 0 ? 'pos' : 'neg' }, money(Math.abs(p.diff), 0, false))),
    h('div', { class: 'progress' }, h('span', { style: { width: `${Math.min(100, Number(p.completion_pct) || 0)}%` } })),
    h('div', { class: 'row-actions', style: { justifyContent: 'space-between' } },
      h('button', { class: 'btn tiny primary', onclick: () => recordForm(p, plan, reload) }, icon('plus', 14), Number(p.actual) > 0 ? 'افزودن واریزی' : 'ثبت واریزی'),
      h('button', { class: 'icon-btn', title: 'ویرایش مبلغ برنامه', onclick: () => editPeriod(p, reload) }, icon('edit', 16)))))));
  root.append(h('div', { class: 'grid charts' },
    chartCard('برنامه در برابر واقعی', () => groupedBarConfig(plan.periods.map((p) => (p.seq === 0 ? 'اولیه' : num(p.seq))), [{ label: 'برنامه', data: plan.periods.map((p) => p.planned), color: '#ffffff33' }, { label: 'واقعی', data: plan.periods.map((p) => p.actual), color: COLORS.green }])),
    h('div', { class: 'card' }, h('h3', { style: { marginBottom: '8px' } }, 'مجموع واریزی و برداشت هر ماه تقویمی'), table([
      { label: 'ماه', render: (m) => m.label }, { label: 'واریزی', class: 'num', render: (m) => money(m.deposits, 0, false) },
      { label: 'برداشت', class: 'num', render: (m) => money(m.withdrawals, 0, false) }, { label: 'خالص', class: 'num', render: (m) => h('span', { class: pnlClass(m.net) }, money(m.net, 0, false)) },
    ], plan.monthly_totals, { empty: 'واریزی ثبت نشده است.' }))));
}
