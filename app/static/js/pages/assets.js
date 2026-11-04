import { api, qs } from '../api.js';
import { state } from '../state.js';
import { reload } from '../app.js';
import { badge, confirmDialog, formModal, h, icon, notice, pageHead, table, toast, typeDot, kpi } from '../ui.js';
import { chartCard, lineConfig, COLORS } from '../charts.js';
import { money, num, pct, signedPct, signedMoney, pnlClass, units, ASSET_TYPE_LABEL, REASON_LABEL, TYPE_LABEL, fmtDate, fmtDateTime } from '../format.js';
import { openTxForm } from './_txform.js';
import { openPriceForm } from './prices.js';
import { weightBar } from './portfolio.js';

export function openAssetForm({ asset = null, onDone } = {}) {
  const currencies = state.meta.currencies.filter((c) => c.is_active);
  const providers = state.meta.price_providers;
  const pp = asset?.price_provider_params || {};
  const fields = [
    { name: 'name', label: 'نام دارایی', type: 'text', required: true },
    { name: 'symbol', label: 'نماد', type: 'text' },
    { name: 'platform_id', label: 'پلتفرم', type: 'select', numeric: true, required: true, options: state.meta.platforms.map((p) => ({ value: p.id, label: p.name })) },
    { name: 'asset_type', label: 'نوع دارایی', type: 'select', options: Object.entries(ASSET_TYPE_LABEL).map(([value, label]) => ({ value, label })) },
    { name: 'target_weight', label: 'وزن هدف در کل سبد (٪)', type: 'decimal', required: true, hint: 'مجموع وزن‌های دارایی‌های فعال باید ۱۰۰٪ باشد.' },
    { name: 'price_currency', label: 'واحد پول قیمت', type: 'select', options: currencies.map((c) => ({ value: c.code, label: `${c.name} (${c.code})` })) },
    { name: 'buy_fee_rate', label: 'کارمزد خرید (٪) برای پیشنهاد خرید', type: 'decimal' },
    { name: 'fractional_units', label: 'خرید اعشاری مجاز است (پیش‌فرض: واحد صحیح)', type: 'checkbox' },
    { name: 'is_active', label: 'دارایی فعال است', type: 'checkbox' },
    { name: 'price_provider', label: 'منبع دریافت خودکار قیمت', type: 'select', options: [{ value: '', label: 'فقط ثبت دستی' }, ...providers.map((p) => ({ value: p.name, label: p.label }))],
      hint: state.meta.price_api_enabled ? undefined : 'دریافت خودکار تا تعریف PRICE_API_ALLOWED_HOSTS در فایل .env غیرفعال است.' },
    { name: 'pp_url', label: 'آدرس منبع قیمت (https)', type: 'text', show: (x) => !!x.price_provider, wide: true },
    { name: 'pp_path', label: 'مسیر قیمت در JSON', type: 'text', show: (x) => !!x.price_provider, placeholder: 'data.price' },
    { name: 'pp_multiplier', label: 'ضریب مقدار دریافتی', type: 'decimal', show: (x) => !!x.price_provider },
    { name: 'note', label: 'توضیحات', type: 'textarea', wide: true },
  ];
  const values = asset ? { ...asset, pp_url: pp.url || '', pp_path: pp.json_path || '', pp_multiplier: pp.multiplier || '1' }
    : { asset_type: 'fund', target_weight: '0', price_currency: 'IRT', buy_fee_rate: '0', is_active: true, platform_id: state.meta.platforms[0]?.id, pp_multiplier: '1' };
  return formModal({
    title: asset ? `ویرایش ${asset.name}` : 'افزودن دارایی جدید', fields, values, wide: true,
    onSubmit: async (x, m) => {
      const body = { platform_id: x.platform_id, name: x.name, symbol: x.symbol || '', asset_type: x.asset_type, target_weight: x.target_weight ?? '0',
        price_currency: x.price_currency, buy_fee_rate: x.buy_fee_rate ?? '0', fractional_units: x.fractional_units, is_active: x.is_active,
        price_provider: x.price_provider || '', note: x.note || '' };
      if (x.price_provider) body.price_provider_params = { url: x.pp_url, json_path: x.pp_path, multiplier: x.pp_multiplier || '1', currency: x.price_currency };
      if (asset) await api.put(`/api/assets/${asset.id}`, body); else await api.post('/api/assets', body);
      m.close(); toast(asset ? 'دارایی ویرایش شد.' : 'دارایی افزوده شد.', 'success'); onDone && onDone();
    },
  });
}

const cardClass = (t) => ({ gold: 't-gold-card', digital: 't-digital-card', index: 't-index-card', fund: 't-fund-card' }[t] || '');

export async function render(root, params) {
  if (params && params[0]) return renderDetail(root, Number(params[0]));
  const res = await api.get('/api/assets');
  root.append(pageHead('دارایی‌ها', 'برای هر دارایی یک صفحه اختصاصی با جزئیات کامل وجود دارد',
    h('button', { class: 'btn primary', onclick: () => openAssetForm({ onDone: reload }) }, icon('plus'), 'دارایی جدید')));
  if (!res.valuation_complete) root.append(notice('برای برخی دارایی‌ها قیمت معتبر امروز ثبت نشده است.'));
  root.append(h('div', { class: 'grid cols-3' }, res.assets.map((a) => {
    const p = a.position;
    return h('a', { class: `card asset-card ${cardClass(a.asset_type)} ${a.is_active ? '' : 'inactive'}`, href: `#/assets/${a.id}` },
      h('h3', null, typeDot(a.asset_type), a.name, a.symbol ? h('small', { class: 'muted' }, a.symbol) : null, a.is_active ? null : badge('غیرفعال')),
      h('div', { class: 'muted', style: { fontSize: '12.5px' } }, `${a.platform} • ${ASSET_TYPE_LABEL[a.asset_type]}`),
      h('div', { class: 'kv' },
        h('div', null, h('span', null, 'ارزش روز'), h('b', null, p?.value === null || p?.value === undefined ? (Number(p?.units) > 0 ? '—' : money(0)) : money(p.value))),
        h('div', null, h('span', null, 'سود/زیان'), h('b', { class: pnlClass(p?.unrealized) }, p?.unrealized == null ? '—' : signedPct(p.unrealized_pct))),
        h('div', null, h('span', null, 'وزن فعلی'), h('b', null, p?.weight == null ? '—' : pct(p.weight, 1))),
        h('div', null, h('span', null, 'وزن هدف'), h('b', null, pct(a.target_weight, 1)))),
      h('div', { style: { marginTop: '10px' } }, weightBar(p?.weight ?? 0, a.target_weight, a.asset_type)));
  })));
}

async function renderDetail(root, id) {
  const a = await api.get(`/api/assets/${id}`);
  const p = a.position, q = p.quote;
  root.append(h('a', { class: 'back-link', href: '#/assets' }, icon('back', 16), 'همه دارایی‌ها'));
  root.append(pageHead(a.name, `${a.platform} • ${ASSET_TYPE_LABEL[a.asset_type]}${a.symbol ? ` • نماد ${a.symbol}` : ''}`,
    h('button', { class: 'btn', onclick: () => openPriceForm({ asset_id: a.id, onDone: reload }) }, icon('price'), 'ثبت قیمت'),
    h('button', { class: 'btn', onclick: () => openTxForm({ defaults: { asset_id: a.id }, onDone: reload }) }, icon('plus'), 'تراکنش'),
    h('button', { class: 'btn', onclick: () => openAssetForm({ asset: a, onDone: reload }) }, icon('edit'), 'ویرایش'),
    h('button', { class: `btn ${a.is_active ? 'danger' : ''}`, onclick: async () => {
      if (a.is_active && !(await confirmDialog({ title: 'غیرفعال کردن', message: `«${a.name}» غیرفعال شود؟ تراکنش‌های قبلی حفظ می‌شود ولی در پیشنهاد خرید و وزن هدف لحاظ نخواهد شد.`, confirmLabel: 'غیرفعال کن', danger: true }))) return;
      await api.post(`/api/assets/${a.id}/active${qs({ active: !a.is_active })}`); toast(a.is_active ? 'دارایی غیرفعال شد.' : 'دارایی فعال شد.', 'success'); reload();
    } }, a.is_active ? 'غیرفعال‌سازی' : 'فعال‌سازی')));
  if (!q?.ok && Number(p.units) > 0) root.append(notice(`قیمت روز معتبر نیست (${q?.reason_text || REASON_LABEL[q?.reason] || 'قیمتی ثبت نشده'}). ${q?.last_price ? `آخرین قیمت ثبت‌شده ${money(q.last_price)} در ${fmtDateTime(q.last_recorded_at)} است و به‌عنوان قیمت روز استفاده نمی‌شود.` : ''}`));
  root.append(h('div', { class: 'card' }, h('div', { class: 'kv kv-3' },
    kv('نام دارایی', a.name), kv('پلتفرم', a.platform), kv('نوع دارایی', ASSET_TYPE_LABEL[a.asset_type]), kv('نماد', a.symbol || '—'),
    kv('تعداد واحد', units(p.units)), kv('میانگین قیمت خرید', p.avg_cost == null ? '—' : money(p.avg_cost, 2)), kv('مجموع مبلغ خرید', money(p.total_bought)), kv('بهای تمام‌شده باقیمانده', money(p.cost_basis)),
    kv('قیمت روز', q?.ok ? `${money(q.price, 2)}${q.currency !== 'IRT' ? ` (${num(q.native_price, 4)} ${q.currency})` : ''}` : '— نامعتبر'), kv('ارزش روز', p.value == null ? '—' : money(p.value)),
    kv('سود یا زیان', p.total_pnl == null ? '—' : h('span', { class: pnlClass(p.total_pnl) }, signedMoney(p.total_pnl))), kv('درصد بازدهی', p.return_pct == null ? '—' : h('span', { class: pnlClass(p.return_pct) }, signedPct(p.return_pct))),
    kv('وزن فعلی در سبد', p.weight == null ? '—' : pct(p.weight, 2)), kv('وزن هدف', pct(a.target_weight, 2)), kv('اختلاف با وزن هدف', p.deviation_pp == null ? '—' : `${p.deviation_pp > 0 ? '+' : ''}${num(p.deviation_pp, 2)} واحد درصد`),
    kv('تحقق‌یافته', h('span', { class: pnlClass(p.realized) }, signedMoney(p.realized))), kv('تحقق‌نیافته', p.unrealized == null ? '—' : h('span', { class: pnlClass(p.unrealized) }, signedMoney(p.unrealized))), kv('سود نقدی', money(p.dividends)))));
  if (a.fx_effect) {
    const f = a.fx_effect;
    root.append(h('h2', { class: 'section-title' }, 'اثر نرخ ارز'), h('div', { class: 'card' }, f.available ? h('div', { class: 'kv kv-3' },
      kv('نرخ میانگین خرید', money(f.fx_rate_avg_cost)), kv('نرخ فعلی', money(f.fx_rate_now)),
      kv('اثر قیمت دارایی', h('span', { class: pnlClass(f.asset_price_effect) }, signedMoney(f.asset_price_effect))), kv('اثر تغییر نرخ ارز', h('span', { class: pnlClass(f.fx_rate_effect) }, signedMoney(f.fx_rate_effect))))
      : h('p', { class: 'muted' }, f.reason)));
  }
  const hist = a.prices.filter((x) => x.is_approved).slice().reverse().map((x) => ({ date: x.recorded_at, price: x.price }));
  root.append(h('div', { class: 'grid', style: { marginTop: '14px' } }, chartCard('تاریخچه قیمت ثبت‌شده', () => (hist.length ? lineConfig(hist, [{ key: 'price', label: `قیمت (${a.price_currency})`, color: COLORS.gold, fill: 'rgba(232,184,74,.1)' }]) : null))));
  root.append(h('h2', { class: 'section-title' }, 'تراکنش‌های دارایی'));
  root.append(h('div', { class: 'card' }, table([
    { label: 'تاریخ', render: (t) => fmtDate(t.tx_date) }, { label: 'نوع', render: (t) => TYPE_LABEL[t.tx_type] },
    { label: 'تعداد', class: 'num', render: (t) => (t.quantity == null ? '—' : units(t.quantity)) }, { label: 'قیمت', class: 'num', render: (t) => (t.unit_price == null ? '—' : money(t.unit_price, 2, false)) },
    { label: 'کارمزد', class: 'num', render: (t) => money(t.fee, 0, false) }, { label: 'مبلغ نهایی', class: 'num', render: (t) => money(t.total_amount) },
  ], a.transactions, { empty: 'تراکنشی برای این دارایی ثبت نشده است.' })));
}
const kv = (k, v) => h('div', null, h('span', null, k), h('b', null, v));
