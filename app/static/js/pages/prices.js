import { api, qs } from '../api.js';
import { state } from '../state.js';
import { reload } from '../app.js';
import { badge, confirmDialog, formModal, h, icon, notice, pageHead, table, toast } from '../ui.js';
import { REASON_LABEL, fmtDateTime, money, num, units } from '../format.js';

export async function openPriceForm({ asset_id = null, onDone } = {}) {
  const assets = (await api.get('/api/assets')).assets;
  const byId = Object.fromEntries(assets.map((a) => [a.id, a]));
  const first = assets.find((a) => a.id === asset_id) || assets.find((a) => a.is_active) || assets[0];
  return formModal({
    title: 'ثبت قیمت دارایی', submitLabel: 'ثبت قیمت',
    fields: [
      { name: 'asset_id', label: 'دارایی', type: 'select', numeric: true, required: true, options: assets.filter((a) => a.is_active || a.id === asset_id).map((a) => ({ value: a.id, label: `${a.name} (${a.platform})` })) },
      { name: 'price', label: 'قیمت', type: 'decimal', required: true, hint: 'به واحد پول دارایی (برای دارایی ارزی: قیمت به همان ارز).' },
      { name: 'recorded_at', label: 'تاریخ و ساعت ثبت', type: 'datetime', required: true },
      { name: 'source', label: 'منبع قیمت', type: 'text', required: true },
      { name: 'is_approved', label: 'قیمت تأیید شده است (در ارزش‌گذاری استفاده شود)', type: 'checkbox', wide: true },
      { name: 'note', label: 'توضیحات', type: 'text', wide: true },
    ],
    values: { asset_id: first?.id, source: 'ثبت دستی', is_approved: true },
    extra: h('div', { class: 'hint', style: { marginBottom: '8px' } }, 'قیمت قدیمی‌تر از حد مجاز (تنظیمات) یا تأییدنشده به‌عنوان «قیمت روز» استفاده نمی‌شود.'),
    onSubmit: async (x, m) => {
      await api.post('/api/prices', { asset_id: x.asset_id, price: x.price, currency: byId[x.asset_id]?.price_currency, recorded_at: x.recorded_at, source: x.source, is_approved: x.is_approved, note: x.note || '' });
      m.close(); toast('قیمت ثبت شد.', 'success'); onDone && onDone();
    },
  });
}

function openFxForm({ onDone }) {
  const cur = state.meta.currencies.filter((c) => !c.is_base && c.is_active);
  if (!cur.length) { toast('ابتدا در تنظیمات یک واحد پول ارزی (مثل USD) اضافه کنید.', 'warn'); return; }
  return formModal({
    title: 'ثبت نرخ تبدیل ارز', submitLabel: 'ثبت نرخ',
    fields: [
      { name: 'currency', label: 'ارز', type: 'select', options: cur.map((c) => ({ value: c.code, label: `${c.name} (${c.code})` })), required: true },
      { name: 'rate', label: 'نرخ (چند تومان برای هر یک واحد ارز)', type: 'decimal', required: true },
      { name: 'recorded_at', label: 'تاریخ و ساعت ثبت', type: 'datetime', required: true },
      { name: 'source', label: 'منبع نرخ', type: 'text', required: true },
      { name: 'is_approved', label: 'تأیید شده است', type: 'checkbox' },
    ],
    values: { source: 'ثبت دستی', is_approved: true },
    onSubmit: async (x, m) => { await api.post('/api/fx', { currency: x.currency, rate: x.rate, recorded_at: x.recorded_at, source: x.source, is_approved: x.is_approved }); m.close(); toast('نرخ ثبت شد.', 'success'); onDone(); },
  });
}

export async function render(root) {
  const [cur, prices, fx] = await Promise.all([api.get('/api/prices/current'), api.get('/api/prices', { limit: 150 }), api.get('/api/fx', { limit: 100 })]);
  root.append(pageHead('قیمت‌ها و نرخ ارز', `قیمت روز فقط وقتی معتبر است که تأییدشده و حداکثر ${num(cur.max_age_days)} روز قدیمی باشد`,
    h('button', { class: 'btn primary', onclick: () => openPriceForm({ onDone: reload }) }, icon('plus'), 'ثبت قیمت'),
    h('button', { class: 'btn', onclick: () => openFxForm({ onDone: reload }) }, icon('plus'), 'ثبت نرخ ارز'),
    h('button', { class: 'btn', onclick: async () => {
      const r = await api.post('/api/prices/fetch');
      if (!r.results.length) toast(state.meta.price_api_enabled ? 'هیچ دارایی‌ای منبع خودکار ندارد؛ در ویرایش دارایی تنظیم کنید.' : 'دریافت خودکار پیکربندی نشده است؛ قیمت‌ها را دستی ثبت کنید.', 'info', 7000);
      r.results.forEach((x) => toast(`${x.asset}: ${x.message}`, x.ok ? 'success' : 'warn', 7000));
      if (r.results.some((x) => x.ok)) reload();
    } }, icon('refresh'), 'دریافت خودکار')));
  if (cur.has_pending) root.append(notice('قیمت‌های در انتظار تأیید وجود دارد؛ تا تأیید نشوند در ارزش‌گذاری استفاده نمی‌شوند.', 'info'));
  root.append(h('h2', { class: 'section-title' }, 'وضعیت قیمت روز'));
  root.append(h('div', { class: 'card' }, table([
    { label: 'دارایی', render: (r) => r.asset },
    { label: 'وضعیت', render: (r) => (r.ok ? badge('معتبر', 'ok') : badge(REASON_LABEL[r.reason] || 'نامعتبر', 'bad')) },
    { label: 'قیمت روز', class: 'num', render: (r) => (r.ok ? `${money(r.price, 2)}${r.currency !== 'IRT' ? ` (${num(r.native_price, 4)} ${r.currency})` : ''}` : '—') },
    { label: 'زمان ثبت', render: (r) => fmtDateTime(r.recorded_at || r.last_recorded_at) },
    { label: 'سن قیمت', render: (r) => (r.age_days == null ? '—' : `${num(r.age_days)} روز`) },
    { label: '', render: (r) => h('button', { class: 'btn tiny', onclick: () => openPriceForm({ asset_id: r.asset_id, onDone: reload }) }, 'ثبت قیمت') },
  ], cur.items.filter((r) => r.active))));
  root.append(h('h2', { class: 'section-title' }, 'تاریخچه قیمت‌ها'));
  root.append(h('div', { class: 'card' }, table([
    { label: 'دارایی', render: (p) => p.asset }, { label: 'قیمت', class: 'num', render: (p) => `${units(p.price)} ${p.currency === 'IRT' ? '' : p.currency}` },
    { label: 'زمان ثبت', render: (p) => fmtDateTime(p.recorded_at) }, { label: 'منبع', render: (p) => p.source },
    { label: 'تأیید', render: (p) => h('button', { class: 'btn tiny', onclick: async () => { await api.post(`/api/prices/${p.id}/approve${qs({ approved: !p.is_approved })}`); reload(); } }, p.is_approved ? badge('تأییدشده', 'ok') : badge('در انتظار تأیید', 'warn')) },
    { label: '', render: (p) => h('button', { class: 'icon-btn', title: 'حذف', onclick: async () => { if (await confirmDialog({ message: 'این قیمت حذف شود؟', danger: true, confirmLabel: 'حذف' })) { await api.del(`/api/prices/${p.id}`); reload(); } } }, icon('trash')) },
  ], prices, { empty: 'قیمتی ثبت نشده است.' })));
  root.append(h('h2', { class: 'section-title' }, 'نرخ تبدیل ارز', h('small', null, 'برای دارایی‌های خارجی؛ تأثیر نرخ روی ارزش تومانی در صفحه سبد نمایش داده می‌شود')));
  root.append(h('div', { class: 'card' }, table([
    { label: 'ارز', render: (r) => r.currency }, { label: 'نرخ (تومان)', class: 'num', render: (r) => money(r.rate, 2, false) },
    { label: 'زمان ثبت', render: (r) => fmtDateTime(r.recorded_at) }, { label: 'منبع', render: (r) => r.source },
    { label: 'تأیید', render: (r) => h('button', { class: 'btn tiny', onclick: async () => { await api.post(`/api/fx/${r.id}/approve${qs({ approved: !r.is_approved })}`); reload(); } }, r.is_approved ? badge('تأییدشده', 'ok') : badge('در انتظار تأیید', 'warn')) },
    { label: '', render: (r) => h('button', { class: 'icon-btn', title: 'حذف', onclick: async () => { if (await confirmDialog({ message: 'این نرخ حذف شود؟', danger: true, confirmLabel: 'حذف' })) { await api.del(`/api/fx/${r.id}`); reload(); } } }, icon('trash')) },
  ], fx, { empty: 'نرخ ارزی ثبت نشده است (فقط برای دارایی‌های ارزی لازم است).' })));
}
