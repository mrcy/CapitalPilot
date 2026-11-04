import { api, qs } from '../api.js';
import { state, typeInfo } from '../state.js';
import { reload, reloadAll } from '../app.js';
import { badge, clear, confirmDialog, formModal, h, icon, modal, notice, pageHead, table, toast, typeDot, kpi } from '../ui.js';
import { chartCard, lineConfig, COLORS } from '../charts.js';
import { money, num, pct, signedPct, signedMoney, pnlClass, units, ASSET_TYPE_LABEL, REASON_LABEL, TYPE_LABEL, fmtDate, fmtDateTime, PROVIDER_STATUS, ORIGIN } from '../format.js';
import { depList, optionsFrom, pager, purgeFlow, toolbar } from '../listkit.js';
import { loadProviders, sourcesEditor } from '../sourceseditor.js';
import { openTxForm } from './_txform.js';
import { openPriceForm } from './prices.js';

// ---------------------------------------------------------------- فرم دارایی
export async function openAssetForm({ asset = null, onDone } = {}) {
  const [{ providers, kinds }, deps] = await Promise.all([loadProviders(), asset ? api.get(`/api/assets/${asset.id}/dependencies`) : Promise.resolve(null)]);
  const currencies = state.meta.currencies.filter((c) => c.is_active);
  const types = state.meta.asset_types.filter((t) => t.is_active || t.key === asset?.asset_type);
  const platforms = state.meta.platforms.filter((p) => !p.is_archived || p.id === asset?.platform_id);
  const hasTx = !!deps?.dependencies.transactions;
  const fields = [
    { type: 'section', name: 's1', label: 'مشخصات' },
    { name: 'name', label: 'نام فارسی', type: 'text', required: true },
    { name: 'name_en', label: 'نام انگلیسی', type: 'text' },
    { ltr: true, name: 'symbol', label: 'نماد', type: 'text' },
    { name: 'asset_type', label: 'نوع دارایی', type: 'select', required: true, options: types.map((t) => ({ value: t.key, label: t.label })), hint: 'نوع جدید را از «مدیریت انواع دارایی» تعریف کنید.' },
    { name: 'platform_id', label: 'پلتفرم', type: 'select', numeric: true, required: true, options: platforms.map((p) => ({ value: p.id, label: p.name })), hint: hasTx ? 'پلتفرم دارایی دارای تراکنش قابل تغییر نیست.' : undefined },
    { name: 'market', label: 'بازار', type: 'text', placeholder: 'مثلاً TSETMC، فرابورس، Bitpin' },
    { type: 'section', name: 's2', label: 'واحد و معامله' },
    { name: 'unit', label: 'واحد سنجش', type: 'text', required: true, placeholder: 'واحد، گرم، سکه، سهم…' },
    { name: 'price_currency', label: 'واحد پول قیمت', type: 'select', options: currencies.map((c) => ({ value: c.code, label: `${c.name} (${c.code})` })) },
    { name: 'decimals', label: 'تعداد اعشار مجاز در مقدار', type: 'int', required: true, hint: '۰ یعنی فقط عدد صحیح.' },
    { name: 'min_quantity', label: 'حداقل مقدار خرید', type: 'decimal' },
    { name: 'buy_fee_rate', label: 'کارمزد خرید (٪) برای پیشنهاد خرید', type: 'decimal' },
    { name: 'initial_price', label: 'قیمت اولیهٔ خرید (اختیاری)', type: 'decimal', hint: 'فقط اطلاعاتی است؛ بهای خرید همیشه از تراکنش‌های واقعی محاسبه می‌شود.' },
    { type: 'section', name: 's3', label: 'سبد و وضعیت' },
    { name: 'target_weight', label: 'وزن هدف در سبد اصلی (٪)', type: 'decimal', required: true, hint: 'وزن در سبدهای دیگر را از صفحهٔ «سبدها» تنظیم کنید.' },
    { name: 'fetch_interval_minutes', label: 'بازهٔ دریافت قیمت این دارایی (دقیقه)', type: 'int', hint: 'خالی = بازهٔ منبع قیمت.' },
    { name: 'is_active', label: 'دارایی فعال است', type: 'checkbox' },
    { name: 'note', label: 'توضیحات', type: 'textarea', wide: true },
  ];
  const values = asset ? { ...asset, fetch_interval_minutes: asset.fetch_interval_minutes ?? '', initial_price: asset.initial_price ?? '' }
    : { asset_type: types[0]?.key || 'other', target_weight: '0', price_currency: 'IRT', buy_fee_rate: '0', is_active: true, platform_id: platforms.find((p) => !p.is_archived)?.id, unit: 'واحد', decimals: 0, min_quantity: '0' };
  let extraVals = { ...(asset?.extra || {}) };
  const extraBox = h('div', { class: 'form-grid' });
  const drawExtra = (key) => {
    const t = typeInfo(key);
    clear(extraBox);
    if (!t?.fields?.length) return;
    extraBox.append(h('div', { class: 'form-section', style: { gridColumn: '1 / -1' } }, `ویژگی‌های «${t.label}»`));
    t.fields.forEach((fd) => {
      const ctl = fd.type === 'select'
        ? h('select', { 'data-key': fd.key }, [h('option', { value: '' }, '—'), ...(fd.options || []).map((o) => h('option', { value: o }, o))])
        : h('input', { type: 'text', 'data-key': fd.key, inputmode: fd.type === 'number' ? 'decimal' : 'text', dir: fd.type === 'number' ? 'ltr' : undefined, class: fd.type === 'number' ? 'ltr-input' : '' });
      ctl.value = extraVals[fd.key] ?? '';
      ctl.addEventListener('input', () => { extraVals[fd.key] = ctl.value; });
      extraBox.append(h('label', null, h('span', { class: 'lbl' }, fd.label), ctl));
    });
  };
  const ed = sourcesEditor({ providers, kinds, initial: asset?.sources || [], currency: asset?.price_currency });
  let lastType = values.asset_type;
  const f = formModal({
    title: asset ? `ویرایش ${asset.name}` : 'افزودن دارایی جدید', fields, values, wide: true,
    onChange: (x) => { if (x.asset_type !== lastType) { lastType = x.asset_type; extraVals = {}; drawExtra(lastType); } },
    onSubmit: async (x, m) => {
      const bad = ed.validate();
      if (bad) throw new Error(bad);
      const extra = {};
      Object.entries(extraVals).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) extra[k] = v; });
      const body = { platform_id: x.platform_id, name: x.name.trim(), name_en: (x.name_en || '').trim(), symbol: (x.symbol || '').trim(), asset_type: x.asset_type, market: (x.market || '').trim(),
        unit: (x.unit || 'واحد').trim(), price_currency: x.price_currency, decimals: x.decimals ?? 0, min_quantity: x.min_quantity ?? '0', target_weight: x.target_weight ?? '0',
        initial_price: x.initial_price === null || x.initial_price === '' ? null : x.initial_price, buy_fee_rate: x.buy_fee_rate ?? '0', is_active: x.is_active,
        fetch_interval_minutes: x.fetch_interval_minutes || null, note: x.note || '', extra, sources: ed.get() };
      if (asset) await api.put(`/api/assets/${asset.id}`, body);
      else await api.post('/api/assets', { ...body, portfolio_id: state.portfolioId });
      m.close(); toast(asset ? 'دارایی ویرایش شد.' : 'دارایی افزوده شد.', 'success'); onDone && onDone();
    },
  });
  if (hasTx) f.refs.platform_id.disabled = true;
  const body = f.modal.el.querySelector('.modal-body');
  f.form.after(extraBox, ed.node);
  drawExtra(lastType);
  return f;
}

// ---------------------------------------------------------------- مدیریت انواع دارایی
const COLOR_OPTS = [['', 'پیش‌فرض'], ['gold', 'طلایی'], ['blue', 'آبی'], ['green', 'سبز'], ['red', 'قرمز'], ['slate', 'خاکستری']];

function openTypeForm({ type = null, onDone }) {
  const rows = [];
  const list = h('div');
  const addRow = (fd = {}) => {
    const key = h('input', { type: 'text', dir: 'ltr', class: 'ltr-input', placeholder: 'کلید لاتین (rate)', value: fd.key || '', 'aria-label': 'کلید فیلد' });
    const label = h('input', { type: 'text', placeholder: 'عنوان فارسی', value: fd.label || '', 'aria-label': 'عنوان فیلد' });
    const ty = h('select', { 'aria-label': 'نوع فیلد' }, [['text', 'متن'], ['number', 'عدد'], ['select', 'انتخابی']].map(([v, l]) => h('option', { value: v }, l)));
    ty.value = fd.type || 'text';
    const opts = h('input', { type: 'text', placeholder: 'گزینه‌ها با ویرگول', value: (fd.options || []).join('،'), 'aria-label': 'گزینه‌ها' });
    const sync = () => { opts.hidden = ty.value !== 'select'; }; ty.addEventListener('change', sync); sync();
    const row = { key, label, ty, opts };
    row.el = h('div', { class: 'src-row', style: { gridTemplateColumns: 'minmax(0,1fr)' } }, key, label, ty, opts,
      h('button', { class: 'btn tiny danger', type: 'button', onclick: () => { rows.splice(rows.indexOf(row), 1); row.el.remove(); } }, 'حذف فیلد'));
    rows.push(row); list.append(row.el);
  };
  (type?.fields || []).forEach(addRow);
  const f = formModal({
    title: type ? `ویرایش نوع «${type.label}»` : 'نوع دارایی جدید',
    fields: [
      { name: 'key', label: 'کلید لاتین (یکتا)', type: 'text', required: true, hint: type ? 'کلید پس از ساخت قابل تغییر نیست.' : 'فقط حروف کوچک انگلیسی، عدد و _ (مثل bond).' },
      { name: 'label', label: 'عنوان فارسی', type: 'text', required: true },
      { name: 'label_en', label: 'عنوان انگلیسی', type: 'text' },
      { name: 'color', label: 'رنگ نمایش', type: 'select', options: COLOR_OPTS.map(([value, label]) => ({ value, label })) },
      { name: 'is_active', label: 'فعال', type: 'checkbox' },
    ],
    values: type ? { ...type } : { color: '', is_active: true },
    submitLabel: 'ذخیره نوع',
    onSubmit: async (x, m) => {
      const fields = rows.map((r) => ({ key: r.key.value.trim(), label: r.label.value.trim(), type: r.ty.value,
        ...(r.ty.value === 'select' ? { options: r.opts.value.split(/[,،]/).map((s) => s.trim()).filter(Boolean) } : {}) })).filter((r) => r.key || r.label);
      const body = { key: x.key.trim(), label: x.label.trim(), label_en: (x.label_en || '').trim(), color: x.color || '', fields, is_active: x.is_active, sort_order: type?.sort_order ?? 100 };
      if (type) await api.put(`/api/asset-types/${type.key}`, body); else await api.post('/api/asset-types', body);
      m.close(); toast('نوع دارایی ذخیره شد.', 'success'); onDone();
    },
  });
  if (type) f.refs.key.disabled = true;
  f.form.after(h('div', { class: 'form-section' }, 'فیلدهای اختصاصی این نوع (اختیاری)'), list, h('button', { class: 'btn tiny', type: 'button', onclick: () => addRow() }, icon('plus', 14), 'افزودن فیلد'));
}

async function openTypesManager() {
  const body = h('div');
  const draw = async () => {
    await reloadAll();
    clear(body);
    const types = await api.get('/api/asset-types');
    body.append(h('div', { class: 'stack-cards' }, types.map((t) => h('div', { class: 'src-row', style: { gridTemplateColumns: 'minmax(0,1fr) auto', alignItems: 'center' } },
      h('div', null, h('b', null, typeDot(t.key), t.label), ' ', h('span', { class: 'muted' }, t.label_en), ' ', t.is_system ? badge('سیستمی', 'info') : badge('سفارشی', 'gold'), t.is_active ? '' : badge('غیرفعال'),
        h('div', { class: 'muted', style: { fontSize: '12px' } }, `${num(t.asset_count)} دارایی • ${num((t.fields || []).length)} فیلد اختصاصی`)),
      h('div', { class: 'row-actions' },
        h('button', { class: 'icon-btn', title: 'ویرایش', 'aria-label': 'ویرایش', onclick: () => openTypeForm({ type: t, onDone: draw }) }, icon('edit', 17)),
        t.is_system || t.asset_count ? null : h('button', { class: 'icon-btn', title: 'حذف', 'aria-label': 'حذف', onclick: async () => { if (await confirmDialog({ message: `نوع «${t.label}» حذف شود؟`, danger: true, confirmLabel: 'حذف' })) { await api.del(`/api/asset-types/${t.key}`); toast('حذف شد.', 'success'); draw(); } } }, icon('trash', 17)))))));
  };
  const m = modal({ title: 'انواع دارایی', wide: true, body, footer: [h('button', { class: 'btn primary', onclick: () => openTypeForm({ onDone: draw }) }, icon('plus'), 'نوع جدید'), h('button', { class: 'btn ghost', onclick: () => { m.close(); reload(); } }, 'بستن')] });
  await draw();
}

// ---------------------------------------------------------------- حذف و بایگانی
export async function deleteAssetFlow(a, onDone) {
  const info = await api.get(`/api/assets/${a.id}/dependencies`);
  const d = info.dependencies;
  if (d.transactions) {
    const ok = await confirmDialog({ title: 'حذف ممکن نیست', message: `«${a.name}» دارای ${num(d.transactions)} تراکنش است و برای حفظ صحت تاریخچه و گزارش‌ها فقط قابل بایگانی است. بایگانی انجام شود؟ (سود و زیان گذشته حفظ می‌شود و بعداً قابل بازیابی است.)`, confirmLabel: 'بایگانی' });
    if (ok) { await api.post(`/api/assets/${a.id}/archive`); toast('دارایی بایگانی شد.', 'success'); onDone(); }
    return;
  }
  const extra = Object.entries(d).filter(([k, n]) => k !== 'transactions' && k !== 'portfolios' && Number(n) > 0);
  if (!extra.length) {
    if (await confirmDialog({ title: 'حذف دارایی', message: `«${a.name}» هیچ تراکنشی ندارد و برای همیشه حذف خواهد شد. ادامه می‌دهید؟`, danger: true, confirmLabel: 'حذف' })) {
      await api.del(`/api/assets/${a.id}`); toast('دارایی حذف شد.', 'success'); onDone();
    }
    return;
  }
  // وابستگی‌هایی مثل قیمت/منبع دارد: حذف دائمی دو مرحله‌ای یا بایگانی
  const m = modal({ title: `حذف «${a.name}»`, body: [h('p', null, 'این دارایی تراکنش ندارد اما داده‌های وابسته دارد:'), depList(d),
    h('p', { class: 'muted' }, 'می‌توانید آن را بایگانی کنید (پیشنهاد می‌شود) یا با تأیید چندمرحله‌ای برای همیشه حذف کنید.')],
  footer: [h('button', { class: 'btn ghost', onclick: () => m.close() }, 'انصراف'),
    h('button', { class: 'btn', onclick: async () => { m.close(); await api.post(`/api/assets/${a.id}/archive`); toast('دارایی بایگانی شد.', 'success'); onDone(); } }, icon('archive', 16), 'بایگانی'),
    h('button', { class: 'btn danger', onclick: () => { m.close(); purgeFlow({ base: `/api/assets/${a.id}`, name: a.name, onDone }); } }, 'حذف دائمی…')] });
}

export async function toggleArchive(a, onDone) {
  if (a.is_archived) { await api.post(`/api/assets/${a.id}/restore`); toast(`«${a.name}» بازیابی شد.`, 'success'); return onDone(); }
  if (await confirmDialog({ title: 'بایگانی دارایی', message: `«${a.name}» بایگانی شود؟ تاریخچه تراکنش‌ها، گزارش‌ها و سود/زیان حفظ می‌شود؛ ولی دیگر در پیشنهاد خرید نمی‌آید و هر زمان قابل بازیابی است.`, confirmLabel: 'بایگانی' })) {
    await api.post(`/api/assets/${a.id}/archive`); toast('دارایی بایگانی شد.', 'success'); onDone();
  }
}

async function refreshOne(a, onDone) {
  const r = await api.post(`/api/assets/${a.id}/refresh-price`);
  const tone = r.ok ? (r.status === 'duplicate' ? 'info' : 'success') : 'warn';
  toast(`${a.name}: ${r.message}${r.ok && r.price ? ` (${money(r.price, 2, false)} ${r.currency || ''})` : ''}`, tone, 8000);
  (r.attempts || []).filter((x) => !x.ok && x.status !== 'disabled').forEach((x) => toast(`${x.provider}: ${x.message}`, 'warn', 9000));
  onDone && onDone();
}

// ---------------------------------------------------------------- فهرست
const F = { q: '', asset_type: '', platform_id: '', status: 'live', sort: 'order', page: 1, size: 12 };
const SORTS = [['order', 'ترتیب پیش‌فرض'], ['name', 'نام (الف تا ی)'], ['name:desc', 'نام (ی تا الف)'], ['symbol', 'نماد'], ['type', 'نوع دارایی'], ['weight', 'وزن هدف (زیاد به کم)'], ['created:desc', 'جدیدترین']];

function priceCell(a) {
  const lp = a.latest_price;
  if (!lp) return badge(a.sources?.length ? 'دریافت نشده' : 'بدون قیمت', 'warn');
  return h('div', null, h('b', null, money(lp.price, 2, false)), lp.currency !== 'IRT' ? ` ${lp.currency}` : '', h('div', null, badge(ORIGIN[lp.origin]?.[0] || '', ORIGIN[lp.origin]?.[1] || ''), ' ', lp.stale ? badge(`قدیمی (${num(lp.age_days)} روز)`, 'warn') : badge(lp.age_days === 0 ? 'امروز' : `${num(lp.age_days)} روز پیش`, 'ok')));
}

const statusBadge = (a) => (a.is_archived ? badge('بایگانی‌شده') : (a.is_active ? badge('فعال', 'ok') : badge('غیرفعال', 'warn')));

export async function render(root, params) {
  if (params && params[0]) return renderDetail(root, Number(params[0]));
  root.append(pageHead('دارایی‌ها و صندوق‌ها', 'همهٔ دارایی‌ها یک ساختار مشترک دارند؛ نوع، پلتفرم و منبع قیمت را آزادانه تغییر دهید.',
    h('button', { class: 'btn primary', onclick: () => openAssetForm({ onDone: reloadAll }) }, icon('plus'), 'دارایی جدید'),
    h('button', { class: 'btn', onclick: async (e) => { e.currentTarget.disabled = true; const r = await api.post('/api/market-data/refresh'); toast(`${num(r.results.filter((x) => x.ok).length)} از ${num(r.results.length)} دارایی به‌روز شد.`, r.results.some((x) => !x.ok) ? 'warn' : 'success'); reload(); } }, icon('refresh'), 'دریافت قیمت‌ها'),
    h('button', { class: 'btn', onclick: openTypesManager }, icon('assets'), 'مدیریت انواع دارایی')));
  const [types, plats] = [state.meta.asset_types, state.meta.platforms];
  const results = h('div');
  const tb = toolbar({
    placeholder: 'جستجو در نام، نام انگلیسی یا نماد…', q: F.q,
    filters: [
      { name: 'asset_type', label: 'نوع', value: F.asset_type, options: optionsFrom(types, (t) => t.key, (t) => t.label, { value: '', label: 'همهٔ نوع‌ها' }) },
      { name: 'platform_id', label: 'پلتفرم', value: F.platform_id, options: optionsFrom(plats, (p) => p.id, (p) => p.name, { value: '', label: 'همهٔ پلتفرم‌ها' }) },
      { name: 'status', label: 'وضعیت', value: F.status, options: [['live', 'فعال و غیرفعال'], ['active', 'فقط فعال'], ['inactive', 'غیرفعال'], ['archived', 'بایگانی‌شده'], ['all', 'همه (با بایگانی)']].map(([value, label]) => ({ value, label })) },
      { name: 'sort', label: 'مرتب‌سازی', value: F.sort, options: SORTS.map(([value, label]) => ({ value, label })) },
    ],
    onChange: (v) => { Object.assign(F, v, { page: 1 }); load(); },
  });
  root.append(tb, results);
  async function load() {
    const [sort, dir] = F.sort.split(':');
    clear(results).append(h('div', { class: 'loading' }, h('div', { class: 'spinner' })));
    const res = await api.get('/api/assets', { q: F.q, asset_type: F.asset_type, platform_id: F.platform_id, status: F.status, sort, desc: dir === 'desc' ? 'true' : '', page: F.page, page_size: F.size });
    clear(results);
    if (!res.valuation_complete) results.append(notice('برای برخی دارایی‌ها قیمت معتبر امروز ثبت نشده است؛ ارزش آن‌ها در جمع کل نمی‌آید.'));
    const done = () => load();
    results.append(h('div', { class: 'card' }, table([
      { label: 'دارایی', render: (a) => h('div', null, h('a', { href: `#/assets/${a.id}` }, h('b', null, typeDot(a.asset_type), a.name)), h('div', { class: 'muted', style: { fontSize: '12px' } }, [a.symbol, a.name_en].filter(Boolean).join(' • ') || '—')) },
      { label: 'نوع', render: (a) => a.asset_type_label },
      { label: 'پلتفرم', render: (a) => a.platform },
      { label: 'ارزش روز', class: 'num', render: (a) => { const p = a.position; return p?.value == null ? (Number(p?.units) > 0 ? badge('بدون قیمت معتبر', 'warn') : '—') : money(p.value); } },
      { label: 'سود/زیان', class: 'num', render: (a) => (a.position?.unrealized == null || !Number(a.position?.units) ? '—' : h('span', { class: pnlClass(a.position.unrealized) }, signedPct(a.position.unrealized_pct))) },
      { label: 'وزن هدف', class: 'num', render: (a) => (a.in_portfolio ? pct(a.portfolio_target_weight, 1) : badge('خارج از سبد')) },
      { label: 'آخرین قیمت', render: priceCell },
      { label: 'وضعیت', render: statusBadge },
      { label: '', render: (a) => h('div', { class: 'row-actions' },
        h('button', { class: 'icon-btn', title: 'ویرایش', 'aria-label': `ویرایش ${a.name}`, onclick: () => openAssetForm({ asset: a, onDone: reloadAll }) }, icon('edit', 17)),
        a.sources?.length && !a.is_archived ? h('button', { class: 'icon-btn', title: 'دریافت قیمت', 'aria-label': `دریافت قیمت ${a.name}`, onclick: () => refreshOne(a, done) }, icon('refresh', 17)) : null,
        h('button', { class: 'icon-btn', title: a.is_archived ? 'بازیابی' : 'بایگانی', 'aria-label': `${a.is_archived ? 'بازیابی' : 'بایگانی'} ${a.name}`, onclick: () => toggleArchive(a, done) }, icon(a.is_archived ? 'restore' : 'archive', 17)),
        h('button', { class: 'icon-btn', title: 'حذف', 'aria-label': `حذف ${a.name}`, onclick: () => deleteAssetFlow(a, done) }, icon('trash', 17))) },
    ], res.assets, { empty: F.q || F.asset_type || F.platform_id ? 'دارایی‌ای با این فیلترها پیدا نشد.' : 'هنوز دارایی‌ای تعریف نشده است.', rowClass: (a) => (a.is_archived ? 'inactive' : '') })),
    pager({ page: F.page, pageSize: F.size, total: res.total, onPage: (p) => { F.page = p; load(); } }));
  }
  await load();
}


async function renderDetail(root, id) {
  const a = await api.get(`/api/assets/${id}`);
  const p = a.position, q = p.quote;
  const done = () => reload();
  root.append(h('a', { class: 'back-link', href: '#/assets' }, icon('back', 16), 'همه دارایی‌ها'));
  root.append(pageHead(a.name, `${a.platform} • ${a.asset_type_label}${a.symbol ? ` • نماد ${a.symbol}` : ''}${a.name_en ? ` • ${a.name_en}` : ''}`,
    a.sources.length && !a.is_archived ? h('button', { class: 'btn', onclick: () => refreshOne(a, done) }, icon('refresh'), 'دریافت قیمت') : null,
    h('button', { class: 'btn', onclick: () => openPriceForm({ asset_id: a.id, onDone: reload }) }, icon('price'), 'ثبت قیمت دستی'),
    a.is_archived ? null : h('button', { class: 'btn', onclick: () => openTxForm({ defaults: { asset_id: a.id }, onDone: reload }) }, icon('plus'), 'تراکنش'),
    h('button', { class: 'btn', onclick: () => openAssetForm({ asset: a, onDone: reloadAll }) }, icon('edit'), 'ویرایش'),
    h('button', { class: 'btn', onclick: () => toggleArchive(a, done) }, icon(a.is_archived ? 'restore' : 'archive'), a.is_archived ? 'بازیابی' : 'بایگانی'),
    h('button', { class: 'btn danger', onclick: () => deleteAssetFlow(a, () => { location.hash = '#/assets'; }) }, icon('trash'), 'حذف')));
  if (a.is_archived) root.append(notice('این دارایی بایگانی شده است: تاریخچه، گزارش‌ها و سود/زیان گذشته حفظ می‌شود ولی در پیشنهاد خرید و تراکنش جدید خرید لحاظ نمی‌شود.', 'info'));
  if (!q?.ok && Number(p.units) > 0) root.append(notice(`قیمت روز معتبر نیست (${q?.reason_text || REASON_LABEL[q?.reason] || 'قیمتی ثبت نشده'}). ${q?.last_price ? `آخرین قیمت ثبت‌شده ${money(q.last_price)} در ${fmtDateTime(q.last_recorded_at)} است و به‌عنوان قیمت روز استفاده نمی‌شود.` : ''}`, 'warn'));
  const extraKv = Object.entries(a.extra || {}).map(([k, v]) => { const fd = typeInfoField(a.asset_type, k); return kv(fd, String(v)); });
  root.append(h('div', { class: 'card' }, h('div', { class: 'kv kv-3' },
    kv('نام دارایی', a.name), kv('پلتفرم', a.platform), kv('نوع دارایی', a.asset_type_label), kv('نماد', a.symbol || '—'),
    kv('واحد سنجش', a.unit), kv('بازار', a.market || '—'), kv('اعشار مجاز', num(a.decimals)), kv('حداقل خرید', Number(a.min_quantity) ? units(a.min_quantity) : '—'),
    ...extraKv,
    kv('تعداد واحد', units(p.units)), kv('میانگین قیمت خرید', p.avg_cost == null ? '—' : money(p.avg_cost, 2)), kv('مجموع مبلغ خرید', money(p.total_bought)), kv('بهای تمام‌شده باقیمانده', money(p.cost_basis)),
    kv('قیمت روز', q?.ok ? `${money(q.price, 2)}${q.currency !== 'IRT' ? ` (${num(q.native_price, 4)} ${q.currency})` : ''}` : (q?.reason === 'no_price' || !q?.last_price ? '— ناموجود' : '— نامعتبر')), kv('ارزش روز', p.value == null ? '—' : money(p.value)),
    kv('سود یا زیان', p.total_pnl == null ? '—' : h('span', { class: pnlClass(p.total_pnl) }, signedMoney(p.total_pnl))), kv('درصد بازدهی', p.return_pct == null ? '—' : h('span', { class: pnlClass(p.return_pct) }, signedPct(p.return_pct))),
    kv(`وزن فعلی در «${a.portfolio.name}»`, p.weight == null ? '—' : pct(p.weight, 2)), kv('وزن هدف', pct(p.target_weight ?? a.target_weight, 2)), kv('اختلاف با وزن هدف', p.deviation_pp == null ? '—' : `${p.deviation_pp > 0 ? '+' : ''}${num(p.deviation_pp, 2)} واحد درصد`),
    kv('تحقق‌یافته', h('span', { class: pnlClass(p.realized) }, signedMoney(p.realized))), kv('تحقق‌نیافته', p.unrealized == null ? '—' : h('span', { class: pnlClass(p.unrealized) }, signedMoney(p.unrealized))), kv('سود نقدی', money(p.dividends)), kv('کارمزدها', money(p.fees)))));
  if (a.fx_effect) {
    const fx = a.fx_effect;
    root.append(h('h2', { class: 'section-title' }, 'اثر نرخ ارز'), h('div', { class: 'card' }, fx.available ? h('div', { class: 'kv kv-3' },
      kv('نرخ میانگین خرید', money(fx.fx_rate_avg_cost)), kv('نرخ فعلی', money(fx.fx_rate_now)),
      kv('اثر قیمت دارایی', h('span', { class: pnlClass(fx.asset_price_effect) }, signedMoney(fx.asset_price_effect))), kv('اثر تغییر نرخ ارز', h('span', { class: pnlClass(fx.fx_rate_effect) }, signedMoney(fx.fx_rate_effect))))
      : h('p', { class: 'muted' }, fx.reason)));
  }
  // منابع قیمت
  root.append(h('h2', { class: 'section-title' }, 'منابع قیمت و اولویت', h('small', null, 'اصلی ← جایگزین ← دستی')));
  root.append(h('div', { class: 'card' }, table([
    { label: 'اولویت', render: (s) => (s.priority === 1 ? badge('اصلی', 'info') : badge(`جایگزین ${num(s.priority - 1)}`)) },
    { label: 'منبع', render: (s) => h('span', null, s.provider, s.is_enabled ? '' : badge('غیرفعال')) },
    { label: 'شناسه', render: (s) => (s.external_id ? h('span', { class: 'kbd' }, s.external_id) : '—') },
    { label: 'آخرین موفق', render: (s) => fmtDateTime(s.last_success_at) },
    { label: 'وضعیت', render: (s) => (s.last_status === 'ok' ? badge('سالم', 'ok') : s.last_status === 'error' ? badge('خطا', 'bad') : badge('—')) },
    { label: 'آخرین خطا', render: (s) => s.last_error || '—' },
  ], a.sources, { empty: 'منبعی تعریف نشده است؛ قیمت فقط دستی ثبت می‌شود. از «ویرایش» منبع اضافه کنید.' })));
  await renderPriceHistory(root, a);
  root.append(h('h2', { class: 'section-title' }, 'تراکنش‌های دارایی', h('small', null, `در «${a.portfolio.name}»`)));
  root.append(h('div', { class: 'card' }, table([
    { label: 'تاریخ', render: (t) => fmtDate(t.tx_date) }, { label: 'نوع', render: (t) => TYPE_LABEL[t.tx_type] },
    { label: 'تعداد', class: 'num', render: (t) => (t.quantity == null ? '—' : units(t.quantity)) }, { label: 'قیمت', class: 'num', render: (t) => (t.unit_price == null ? '—' : money(t.unit_price, 2, false)) },
    { label: 'کارمزد', class: 'num', render: (t) => money(t.fee, 0, false) }, { label: 'مبلغ نهایی', class: 'num', render: (t) => money(t.total_amount) },
  ], a.transactions, { empty: 'تراکنشی برای این دارایی ثبت نشده است.' })));
}

function typeInfoField(typeKey, key) { return typeInfo(typeKey)?.fields?.find((f) => f.key === key)?.label || key; }

async function renderPriceHistory(root, a) {
  const box = h('div');
  root.append(h('h2', { class: 'section-title' }, 'تاریخچهٔ قیمت و مقایسهٔ منابع'), box);
  let days = 90;
  const draw = async () => {
    clear(box).append(h('div', { class: 'loading' }, h('div', { class: 'spinner' })));
    const hs = await api.get('/api/market-data/history', { asset_id: a.id, days });
    clear(box);
    const sel = h('select', { 'aria-label': 'بازهٔ نمودار', style: { maxWidth: '160px' } }, [[30, '۳۰ روز'], [90, '۹۰ روز'], [365, 'یک سال'], [1825, 'پنج سال']].map(([v, l]) => h('option', { value: v }, l)));
    sel.value = String(days); sel.addEventListener('change', () => { days = Number(sel.value); draw(); });
    const imports = a.sources.filter((s) => ['tsetmc', 'bitpin'].includes(s.provider_kind) || s.provider_kind === 'custom_api');
    const bar = h('div', { class: 'inline-form', style: { marginBottom: '10px' } }, h('label', null, h('span', { class: 'lbl' }, 'بازه'), sel),
      ...imports.map((s) => h('button', { class: 'btn tiny', onclick: async (e) => {
        e.currentTarget.disabled = true;
        try { const r = await api.post('/api/market-data/history/import', { asset_id: a.id, provider_id: s.provider_id, days: Math.min(days, 3650) }); toast(`از ${s.provider}: ${num(r.stored)} قیمت جدید ثبت شد (${num(r.duplicates)} تکراری، ${num(r.invalid)} نامعتبر).`, 'success', 7000); draw(); } catch { e.currentTarget.disabled = false; }
      } }, icon('download', 14), `دریافت تاریخچه از ${s.provider}`)));
    box.append(bar);
    const series = hs.series.map((s, i) => ({ key: `p${i}`, label: s.name, color: [COLORS.gold, COLORS.indigo, COLORS.green, COLORS.blue, COLORS.red][i % 5], pts: s.points.filter((x) => x.is_valid && x.is_approved) }));
    const times = [...new Set(series.flatMap((s) => s.pts.map((x) => x.t)))].sort();
    const pts = times.map((t) => { const o = { date: t }; series.forEach((s) => { const x = s.pts.find((y) => y.t === t); o[s.key] = x ? x.price : null; }); return o; });
    box.append(h('div', { class: 'grid' }, chartCard(`قیمت (${a.price_currency}) — فقط قیمت‌های معتبر و تأییدشده`, () => (pts.length ? lineConfig(pts, series.map((s) => ({ key: s.key, label: s.name || s.label, color: s.color }))) : null), { sub: 'قیمت نامعتبر یا تأییدنشده در نمودار و ارزش‌گذاری نمی‌آید' })));
    box.append(h('div', { class: 'card', style: { marginTop: '14px' } }, h('h3', { style: { marginBottom: '8px', fontSize: '14.5px' } }, 'مقایسهٔ منابع'), table([
      { label: 'منبع', render: (c) => c.name }, { label: 'آخرین قیمت معتبر', class: 'num', render: (c) => (c.last_price == null ? '—' : money(c.last_price, 2, false)) },
      { label: 'زمان', render: (c) => fmtDateTime(c.last_time) }, { label: 'اختلاف با اولین منبع', class: 'num', render: (c) => (c.diff_pct == null ? '—' : signedPct(c.diff_pct)) },
      { label: 'تعداد', class: 'num', render: (c) => num(c.count) }, { label: 'نامعتبر', class: 'num', render: (c) => (c.invalid_count ? badge(num(c.invalid_count), 'bad') : '۰') },
    ], hs.comparison, { empty: 'هنوز قیمتی ثبت نشده است.' })));
    box.append(h('h3', { style: { margin: '18px 0 8px', fontSize: '14.5px' } }, 'آخرین قیمت‌های ثبت‌شده'));
    box.append(h('div', { class: 'card' }, table([
      { label: 'زمان منبع/ثبت', render: (x) => fmtDateTime(x.source_time || x.recorded_at) }, { label: 'زمان دریافت', render: (x) => (x.fetched_at ? fmtDateTime(x.fetched_at) : '—') },
      { label: 'قیمت', class: 'num', render: (x) => `${units(x.price)} ${x.currency === 'IRT' ? '' : x.currency}` }, { label: 'منبع', render: (x) => x.source + (x.price_kind ? ` (${{ last: 'آخرین معامله', close: 'پایانی', nav: 'NAV' }[x.price_kind] || x.price_kind})` : '') },
      { label: 'اعتبار', render: (x) => (x.is_valid ? badge('معتبر', 'ok') : h('span', { title: x.validity_note }, badge('نامعتبر', 'bad'))) },
      { label: 'تأیید', render: (x) => h('button', { class: 'btn tiny', onclick: async () => { await api.post(`/api/prices/${x.id}/approve${qs({ approved: !x.is_approved })}`); reload(); } }, x.is_approved ? badge('تأییدشده', 'ok') : badge('تأییدنشده', 'warn')) },
    ], a.prices.slice(0, 15), { empty: 'قیمتی ثبت نشده است.' })));
  };
  await draw();
}
const kv = (k, v) => h('div', null, h('span', null, k), h('b', null, v));
