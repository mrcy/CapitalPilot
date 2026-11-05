import { api } from '../api.js';
import { reload } from '../app.js';
import { badge, buildForm, clear, h, icon, kpi, notice, pageHead, table, typeDot } from '../ui.js';
import { money, num, pct, signedPct, units, parseDecimal, faDigits, todayISO } from '../format.js';
import { weightBar } from './portfolio.js';
import { openTxForm } from './_txform.js';

const STATUS = { buy: ['info', 'خرید'], above_target: ['muted', 'بالاتر از هدف — بدون خرید'], too_small: ['warn', 'مبلغ برای یک واحد کافی نیست'], no_price: ['bad', 'قیمت معتبر ثبت نشده'] };

export async function render(root) {
  let source = 'monthly', custom = '';
  const out = h('div');
  const tabs = h('div', { class: 'tabs' });
  const amountForm = buildForm([{ name: 'amount', label: 'مبلغ دلخواه (تومان)', type: 'decimal' }], {});
  amountForm.form.style.maxWidth = '320px';
  amountForm.form.addEventListener('submit', (e) => { e.preventDefault(); run(); });
  amountForm.form.addEventListener('change', () => { if (source === 'custom') run(); });

  const defs = { monthly: 'واریزی ماهانه برنامه', cash: 'نقدینگی موجود', custom: 'مبلغ دلخواه' };
  function drawTabs(d) {
    clear(tabs);
    Object.entries(defs).forEach(([k, label]) => tabs.append(h('button', { class: `tab ${source === k ? 'active' : ''}`, onclick: () => { source = k; drawTabs(d); amountForm.form.hidden = k !== 'custom'; run(); } },
      label, d && k !== 'custom' ? ` — ${money(d[k], 0, false)}` : '')));
  }
  async function run() {
    const v = amountForm.getValues();
    if (source === 'custom' && !v.amount) { clear(out).append(notice('مبلغ دلخواه را وارد کنید.', 'info')); return; }
    const r = await api.get('/api/rebalance', { source, amount: source === 'custom' ? v.amount : undefined });
    drawTabs(r.defaults);
    draw(r);
  }
  function draw(r) {
    clear(out);
    if (!r.available) { out.append(notice(r.reason, 'warn')); return; }
    r.warnings.forEach((w) => out.append(notice(w)));
    r.notes.forEach((w) => out.append(notice(w, 'info')));
    out.append(h('div', { class: 'grid kpis' },
      kpi({ label: 'مبلغ قابل تخصیص', value: money(r.amount), tone: 'accent' }),
      kpi({ label: 'مجموع خرید پیشنهادی', value: money(r.total_spend), sub: 'شامل کارمزد' }),
      kpi({ label: 'باقیمانده (گرد کردن واحد صحیح)', value: money(r.leftover) }),
      kpi({ label: 'ارزش دارایی‌ها پس از خرید', value: money(Number(r.invested_value) + Number(r.total_spend)) }),
      kpi({ label: 'واریز لازم برای رسیدن به هدف بدون فروش', hint: 'کمترین مبلغ جدیدی که اگر فقط به دارایی‌های عقب‌مانده برود، همه را به وزن هدف می‌رساند.', value: money(r.extra_to_reach_target_without_selling), tone: 'gold' }),
    ));
    out.append(h('h2', { class: 'section-title' }, 'پیشنهاد خرید هر دارایی'));
    out.append(h('div', { class: 'card' }, table([
      { label: 'دارایی', render: (x) => h('b', null, typeDot(x.asset_type), x.name) },
      { label: 'وزن فعلی ← هدف', render: (x) => h('div', null, weightBar(x.current_weight, x.target_weight, x.asset_type), h('small', { class: 'muted' }, `${pct(x.current_weight, 1)} از ${pct(x.target_weight, 1)} (${x.deviation_pp > 0 ? '+' : ''}${num(x.deviation_pp, 1)})`)) },
      { label: 'مبلغ ایده‌آل', class: 'num', render: (x) => money(x.ideal_amount, 0, false) },
      { label: 'قیمت روز', class: 'num', render: (x) => (x.price === null ? '—' : money(x.price, 2, false)) },
      { label: 'تعداد واحد', class: 'num', render: (x) => h('b', null, units(x.units)) },
      { label: 'مبلغ نهایی (کارمزد)', class: 'num', render: (x) => h('div', null, h('b', null, money(x.total_cost, 0, false)), h('div', { class: 'muted small-text' }, `کارمزد: ${money(x.fee, 0, false)}`)) },
      { label: 'وزن پس از خرید', class: 'num', render: (x) => pct(x.weight_after, 1) },
      { label: 'وضعیت', render: (x) => badge(STATUS[x.status][1], STATUS[x.status][0]) },
      { label: '', render: (x) => (Number(x.units) > 0 ? h('button', { class: 'btn tiny', title: 'پس از انجام خرید در پلتفرم، آن را ثبت کنید', onclick: () => openTxForm({ defaults: { tx_type: 'buy', asset_id: x.asset_id, quantity: x.units, unit_price: x.price, fee: x.fee, tx_date: todayISO(), record_price: true }, onDone: reload }) }, 'ثبت پس از خرید') : null) },
    ], r.rows, { compact: true })));
    out.append(h('h2', { class: 'section-title' }, 'مبلغ لازم در هر پلتفرم'));
    out.append(h('div', { class: 'grid cols-3' }, r.by_platform.map((p) => kpi({ label: p.platform, value: money(p.amount) }))));
    out.append(h('div', { style: { marginTop: '16px' } }, notice(r.disclaimer, 'info')));
  }
  root.append(pageHead('پیشنهاد خرید و متعادل‌سازی', 'تخصیص واریزی جدید با اولویت دارایی‌های کمتر از وزن هدف — بدون پیشنهاد فروش'), tabs, amountForm.form, out);
  amountForm.form.hidden = true;
  await run();
}
