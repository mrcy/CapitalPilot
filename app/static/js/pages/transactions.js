import { api } from '../api.js';
import { state, calendar } from '../state.js';
import { reload } from '../app.js';
import { badge, buildForm, clear, confirmDialog, dateField, h, icon, pageHead, table, toast, toastWarnings, loadingBox } from '../ui.js';
import { TYPE_LABEL, fmtDate, money, num, units, pnlClass } from '../format.js';
import { openTxForm } from './_txform.js';

const KIND = { buy: 'info', sell: 'warn', deposit: 'ok', withdrawal: 'bad', dividend: 'ok', fee: 'muted', adjustment: 'gold' };
const PAGE = 100;

export async function render(root) {
  const assets = (await api.get('/api/assets')).assets;
  const f = { tx_type: '', platform_id: '', asset_id: '', q: '' };
  const from = dateField('from', '', { required: false }), to = dateField('to', '', { required: false });
  const form = buildForm([
    { name: 'tx_type', label: 'نوع', type: 'select', options: [{ value: '', label: 'همه' }, ...Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))] },
    { name: 'platform_id', label: 'پلتفرم', type: 'select', options: [{ value: '', label: 'همه' }, ...state.meta.platforms.map((p) => ({ value: p.id, label: p.name }))] },
    { name: 'asset_id', label: 'دارایی', type: 'select', options: [{ value: '', label: 'همه' }, ...assets.map((a) => ({ value: a.id, label: a.name }))] },
    { name: 'q', label: 'جستجو', type: 'text', placeholder: 'توضیحات یا نام دارایی' },
  ], f);
  form.form.className = 'filters';
  form.form.append(h('label', null, h('span', { class: 'lbl' }, 'از تاریخ'), from), h('label', null, h('span', { class: 'lbl' }, 'تا تاریخ'), to));
  const listBox = h('div'), moreBox = h('div', { style: { textAlign: 'center', marginTop: '12px' } });
  let offset = 0, loaded = [];

  async function load(reset = true) {
    if (reset) { offset = 0; loaded = []; }
    const v = form.getValues();
    const res = await api.get('/api/transactions', { tx_type: v.tx_type, platform_id: v.platform_id, asset_id: v.asset_id, q: v.q, date_from: from.getValue(), date_to: to.getValue(), limit: PAGE, offset });
    loaded = loaded.concat(res.items); offset += res.items.length;
    clear(listBox).append(table([
      { label: 'تاریخ', render: (t) => fmtDate(t.tx_date) },
      { label: 'نوع', render: (t) => badge(TYPE_LABEL[t.tx_type], KIND[t.tx_type]) },
      { label: 'پلتفرم', render: (t) => t.platform },
      { label: 'دارایی', render: (t) => t.asset || '—' },
      { label: 'تعداد', class: 'num', render: (t) => (t.quantity !== null ? units(t.quantity) : '—') },
      { label: 'قیمت واحد', class: 'num', render: (t) => (t.unit_price !== null ? money(t.unit_price, 2, false) : '—') },
      { label: 'کارمزد', class: 'num', render: (t) => (Number(t.fee) ? money(t.fee, 0, false) : '—') },
      { label: 'مبلغ نهایی', class: 'num', render: (t) => h('b', { class: ['deposit', 'sell', 'dividend'].includes(t.tx_type) ? 'pos' : ['withdrawal', 'buy', 'fee'].includes(t.tx_type) ? 'neg' : '' }, money(t.total_amount)) },
      { label: 'توضیحات', class: 'wrap', render: (t) => t.note || '' },
      { label: '', render: (t) => h('div', { class: 'row-actions' },
        h('button', { class: 'icon-btn', title: 'ویرایش', onclick: () => openTxForm({ tx: t, onDone: () => load() }) }, icon('edit')),
        h('button', { class: 'icon-btn', title: 'حذف', onclick: () => del(t) }, icon('trash'))) },
    ], loaded, { empty: 'هنوز تراکنشی ثبت نشده است. با دکمه «تراکنش جدید» شروع کنید.' }));
    clear(moreBox);
    if (loaded.length < res.total) moreBox.append(h('button', { class: 'btn', onclick: () => load(false) }, `نمایش بیشتر (${num(res.total - loaded.length)} مورد دیگر)`));
    summary.textContent = `${num(res.total)} تراکنش`;
  }
  async function del(t) {
    const ok = await confirmDialog({ title: 'حذف تراکنش', danger: true, confirmLabel: 'حذف', message: `تراکنش «${TYPE_LABEL[t.tx_type]}» به تاریخ ${fmtDate(t.tx_date)} حذف شود؟ موجودی، میانگین قیمت و سود و زیان بازمحاسبه می‌شود.` });
    if (!ok) return;
    const res = await api.del(`/api/transactions/${t.id}`);
    toast('تراکنش حذف شد.', 'success'); toastWarnings(res.warnings); load();
  }
  const summary = h('span', { class: 'muted' });
  root.append(pageHead('تراکنش‌ها', 'ثبت خرید، فروش، واریز، برداشت، سود نقدی، کارمزد و اصلاح موجودی',
    h('button', { class: 'btn primary', onclick: () => openTxForm({ onDone: () => load() }) }, icon('plus'), 'تراکنش جدید')),
    h('div', { class: 'card' }, form.form, h('div', { class: 'inline-form', style: { marginBottom: '10px' } }, h('button', { class: 'btn', onclick: () => load() }, 'اعمال فیلتر'), summary), listBox, moreBox));
  form.form.addEventListener('change', () => load());
  from.addEventListener('change', () => load()); to.addEventListener('change', () => load());
  form.form.addEventListener('submit', (e) => { e.preventDefault(); load(); });
  await load();
}
