// مرکز هوشمندی قیمت‌ها: سلامت منابع، پایش قیمت دارایی‌ها، هشدارهای هوشمند، گزارش عملکرد و لاگ‌ها.
// این صفحه فقط می‌خواند، تحلیل و پیشنهاد می‌دهد؛ هیچ سفارش خرید یا فروشی ثبت نمی‌شود.
import { api } from '../api.js';
import { reload } from '../app.js';
import { COLORS, chartCard } from '../charts.js';
import { badge, buildForm, clear, dateField, h, icon, loadingBox, modal, notice, pageHead, table, toast } from '../ui.js';
import { FLAG_LABEL, ORIGIN, PRICE_STATUS, PROVIDER_STATUS, fmtDate, fmtDateTime, money, num, units } from '../format.js';
import { loadProviders, sourcesEditor } from '../sourceseditor.js';
import { openPriceForm } from './prices.js';

const TABS = [['overview', 'نمای کلی منابع'], ['assets', 'پایش قیمت دارایی‌ها'], ['alerts', 'هشدارهای هوشمند'], ['performance', 'گزارش عملکرد'], ['logs', 'تاریخچهٔ درخواست‌ها']];
const SEVERITY = { critical: ['بحرانی', 'critical'], warning: ['هشدار', 'warning'], info: ['اطلاع', 'info'] };
const LOG_STATUS = { ok: ['موفق', 'ok'], duplicate: ['تکراری', ''], error: ['خطا', 'bad'], invalid: ['نامعتبر', 'bad'], stale: ['قدیمی', 'warn'], rate_limited: ['محدودیت نرخ', 'warn'] };
const PALETTE = [COLORS.blue, COLORS.green, COLORS.gold, COLORS.indigo, COLORS.teal, COLORS.red, COLORS.slate];

const statusBadge = (s) => { const [t, k] = PRICE_STATUS[s] || [s, '']; return badge(t, k); };
const originBadge = (o) => { const [t, k] = ORIGIN[o] || [o, '']; return badge(t, k); };
const priceText = (price, cur) => (price === null || price === undefined ? '—' : cur === 'IRT' ? money(price, 2) : `${units(price)} ${cur}`);
const ltr = (t) => h('span', { dir: 'ltr', class: 'ltr-text' }, t);

function ageText(minutes) {
  if (minutes === null || minutes === undefined) return '—';
  if (minutes < 1) return 'هم‌اکنون';
  if (minutes < 60) return `${num(minutes)} دقیقه پیش`;
  if (minutes < 1440) return `${num(Math.floor(minutes / 60))} ساعت پیش`;
  return `${num(Math.floor(minutes / 1440))} روز پیش`;
}
function delayText(sec) {
  if (sec === null || sec === undefined) return '—';
  if (sec < 60) return 'کمتر از یک دقیقه';
  if (sec < 3600) return `${num(Math.round(sec / 60))} دقیقه`;
  return `${num(Math.round(sec / 360) / 10)} ساعت`;
}
const msText = (ms) => (ms === null || ms === undefined ? '—' : `${num(ms)} میلی‌ثانیه`);
const rateBadge = (r) => (r === null || r === undefined ? badge('بدون درخواست', '') : badge(`${num(r, 1)}٪`, r >= 90 ? 'ok' : r >= 60 ? 'warn' : 'bad'));

function tabs(active) {
  return h('nav', { class: 'tabs', 'aria-label': 'بخش‌های مرکز هوشمندی' }, TABS.map(([k, label]) => h('a', { class: `tab ${k === active ? 'active' : ''}`, href: `#/intelligence/${k}`, 'aria-current': k === active ? 'page' : null }, label)));
}
function windowChips(current, onPick) {
  return h('div', { class: 'chips', role: 'group', 'aria-label': 'بازهٔ زمانی' }, [[1, '۲۴ ساعت'], [7, '۷ روز'], [30, '۳۰ روز'], [90, '۹۰ روز']].map(([d, l]) => h('button', { type: 'button', class: `tab ${d === current ? 'active' : ''}`, onclick: () => onPick(d) }, l)));
}

// ---------------------------------------------------------------- نمای کلی
async function overviewTab(root, days) {
  const [ov, al] = await Promise.all([api.get('/api/market-data/intelligence/overview', { days }), api.get('/api/market-data/intelligence/alerts')]);
  const s = ov.summary;
  if (al.counts.critical) root.append(h('a', { href: '#/intelligence/alerts', class: 'alert-link' }, notice(`${num(al.counts.critical)} هشدار بحرانی و ${num(al.counts.warning)} هشدار دیگر وجود دارد؛ برای مشاهده کلیک کنید.`, 'bad')));
  else if (al.total) root.append(h('a', { href: '#/intelligence/alerts', class: 'alert-link' }, notice(`${num(al.total)} هشدار فعال وجود دارد؛ برای مشاهده کلیک کنید.`, 'warn')));
  root.append(h('div', { class: 'toolbar-row' }, h('span', { class: 'muted' }, 'بازهٔ آمار:'), windowChips(days, (d) => { location.hash = `#/intelligence/overview/${d}`; })));
  root.append(h('div', { class: 'grid kpis k6' },
    kpiCard('منابع فعال', num(s.enabled), `از ${num(s.total)} منبع`, 'green'),
    kpiCard('منابع غیرفعال', num(s.disabled), 'در دریافت خودکار شرکت نمی‌کنند', ''),
    kpiCard('منابع دارای خطا', num(s.error), s.error ? 'آخرین ارتباط ناموفق بوده' : 'خطایی ثبت نشده', s.error ? 'red' : 'green'),
    kpiCard('آخرین دریافت موفق', s.last_success_at ? h('span', { class: 'kpi-small' }, fmtDateTime(s.last_success_at)) : '—', s.last_success_at ? '' : 'هنوز دریافتی موفق ثبت نشده است', 'blue'),
    kpiCard('نرخ موفقیت درخواست‌ها', s.success_rate === null ? '—' : `${num(s.success_rate, 1)}٪`, `${num(s.requests)} درخواست، ${num(s.errors)} خطا`, s.success_rate !== null && s.success_rate < 80 ? 'red' : 'accent'),
    kpiCard('میانگین زمان پاسخ', msText(s.avg_latency_ms), 'فقط درخواست‌های موفق', 'gold'),
  ));
  root.append(h('h2', { class: 'section-title' }, 'وضعیت زندهٔ منابع', h('small', null, 'بر پایهٔ لاگ واقعی درخواست‌ها؛ منبع آزمایش‌نشده «آزمایش‌نشده» نمایش داده می‌شود')));
  root.append(h('div', { class: 'card' }, table([
    { label: 'منبع', render: (p) => [h('b', null, p.name), h('div', { class: 'muted small-text' }, p.kind_label)] },
    { label: 'وضعیت', render: (p) => { const [t, k] = PROVIDER_STATUS[p.is_enabled ? p.status : 'disabled'] || [p.status, '']; return [badge(t, k), p.last_error && p.is_enabled ? h('div', { class: 'muted small-text err-line', title: p.last_error }, p.last_error.slice(0, 70)) : null]; } },
    { label: 'آخرین دریافت موفق', render: (p) => (p.last_success_at ? fmtDateTime(p.last_success_at) : '—') },
    { label: 'زمان پاسخ (آخرین / میانگین)', render: (p) => (p.kind === 'manual' ? '—' : h('div', null, msText(p.last_latency_ms), h('div', { class: 'muted small-text' }, `میانگین: ${msText(p.avg_latency_ms)}`))) },
    { label: 'درصد موفقیت', render: (p) => (p.kind === 'manual' ? '—' : rateBadge(p.success_rate)) },
    { label: 'درخواست / خطا', class: 'num', render: (p) => (p.kind === 'manual' ? '—' : [num(p.requests), ' / ', p.errors ? h('b', { class: 'neg' }, num(p.errors)) : num(0)]) },
    { label: 'خطای پیاپی', class: 'num', render: (p) => num(p.consecutive_failures) },
  ], ov.providers)));
  root.append(h('p', { class: 'sticky-note' }, `آستانه‌ها: اختلاف منابع بیش از ${num(ov.thresholds.conflict_pct)}٪، تغییر ناگهانی بیش از ${num(ov.thresholds.jump_pct)}٪، فاصلهٔ زمان منبع با دریافت بیش از ${num(ov.thresholds.max_lag_minutes)} دقیقه و قطع منبع پس از ${num(ov.thresholds.provider_down_failures)} خطای پیاپی (قابل تنظیم با متغیرهای محیطی QUALITY_*).`));
}
const kpiCard = (label, value, sub, tone) => h('div', { class: `card kpi ${tone}` }, h('div', { class: 'kpi-label' }, label), h('div', { class: 'kpi-value' }, value), sub ? h('div', { class: 'kpi-sub' }, sub) : null);

// ---------------------------------------------------------------- پایش دارایی‌ها
function chainView(r) {
  if (!r.has_sources) return h('span', { class: 'muted' }, 'بدون منبع (فقط دستی)');
  return h('div', { class: 'chain' }, r.sources.map((x, i) => {
    const bad = x.last_status === 'error' || !x.provider_enabled || !x.is_enabled;
    const used = r.last_good && r.last_good.provider_id === x.provider_id && r.last_good.origin === 'online';
    return h('span', { class: `chain-item ${x.role} ${bad ? 'down' : ''} ${used ? 'used' : ''}`, title: `${x.role === 'primary' ? 'منبع اصلی' : 'جایگزین'}${bad ? ' — خطا/غیرفعال' : ''}${used ? ' — منبع قیمت فعلی' : ''}` },
      i ? h('span', { class: 'chain-arrow', 'aria-hidden': 'true' }, '←') : null, x.provider, bad ? ' ✕' : (used ? ' ✓' : ''));
  }));
}

function openDetails(r) {
  const lg = r.last_good;
  const rows = [];
  const kv = (k, v) => h('div', { class: 'summary-item' }, h('span', null, k), h('b', null, v));
  const body = [h('div', { class: 'summary-grid' },
    kv('وضعیت', statusBadge(r.status)), kv('قیمت فعلی', priceText(r.price, r.currency)), kv('منبع قیمت', r.source ? [r.source, ' ', originBadge(r.origin)] : '—'),
    kv('زمان ثبت قیمت', r.recorded_at ? fmtDateTime(r.recorded_at) : '—'), kv('سن قیمت', ageText(r.age_minutes)), kv('تأخیر داده (منبع تا دریافت)', delayText(r.delay_seconds)))];
  if (r.reason && !['valid', 'manual'].includes(r.status)) body.push(notice(r.reason, r.status === 'conflict' || r.status === 'invalid' ? 'bad' : 'warn'));
  if (r.primary_down) body.push(notice(`منبع اصلی این دارایی پاسخ نمی‌دهد${r.using_fallback ? '؛ قیمت از منبع جایگزین/دستی گرفته شده است.' : '؛ منبع جایگزین معتبری در دسترس نیست.'}`, 'warn'));
  else if (r.using_fallback) body.push(notice('قیمت فعلی از منبع جایگزین گرفته شده است، نه منبع اصلی.', 'info'));
  // مقایسهٔ منابع
  const c = r.comparison;
  body.push(h('h4', { class: 'section-title' }, 'مقایسهٔ منابع', c.spread_pct !== null && c.spread_pct !== undefined ? h('small', null, `بیشترین اختلاف: ${num(c.spread_pct, 2)}٪ (آستانه ${num(c.threshold_pct)}٪)`) : null));
  body.push(c.rows.length ? table([
    { label: 'منبع', render: (x) => [x.source, ' ', originBadge(x.origin)] },
    { label: 'قیمت', class: 'num', render: (x) => priceText(x.price, r.currency) },
    { label: 'زمان', render: (x) => fmtDateTime(x.recorded_at) },
    { label: 'سن', render: (x) => ageText(x.age_minutes) },
    { label: 'اختلاف با میانه', class: 'num', render: (x) => (x.diff_pct === null || x.diff_pct === undefined ? '—' : `${num(x.diff_pct, 2)}٪`) },
  ], c.rows) : h('div', { class: 'empty-note' }, 'قیمت معتبر تازه‌ای برای مقایسه وجود ندارد.'));
  if (c.conflict) body.push(notice('اختلاف بین منابع از آستانه بیشتر است؛ سیستم قیمتی را خودکار انتخاب نمی‌کند. قیمت دستی ثبت کنید یا یکی از قیمت‌ها را در «قیمت‌ها و نرخ ارز» صریحاً تأیید کنید.', 'bad'));
  // ردپای تبدیل
  if (lg) {
    body.push(h('h4', { class: 'section-title' }, 'ردپای تبدیل و ثبت'));
    const trace = [];
    if (lg.origin === 'online') {
      trace.push(h('div', null, 'مقدار خام دریافتی: ', lg.raw_price !== null && lg.raw_price !== undefined ? [ltr(units(lg.raw_price)), ` ${lg.raw_unit || ''}`] : '—'));
      trace.push(h('div', null, 'تبدیل: ', lg.conversion_note || 'بدون تبدیل (واحد منبع با واحد دارایی یکسان است).'));
      trace.push(h('div', null, 'زمان منبع: ', lg.source_time ? fmtDateTime(lg.source_time) : 'اعلام نشده', ' — زمان دریافت: ', lg.fetched_at ? fmtDateTime(lg.fetched_at) : '—'));
      if (lg.via?.length) trace.push(h('div', null, 'مسیر دریافت: ', lg.via.map((v, i) => [i ? ' ← ' : '', `${v.provider} (${v.status === 'ok' ? 'موفق' : v.status === 'duplicate' ? 'موفق/تکراری' : 'ناموفق'})`])));
    } else trace.push(h('div', null, 'این قیمت را کاربر به‌صورت دستی ثبت کرده است.'));
    if (lg.flags?.length) trace.push(h('div', { class: 'chips' }, lg.flags.map((f) => h('span', { class: 'chip' }, FLAG_LABEL[f] || f))));
    if (r.fx) trace.push(h('div', null, 'نرخ ارز برای تبدیل به تومان: ', r.fx.rate ? [ltr(units(r.fx.rate)), ` (${r.fx.source}، ${fmtDateTime(r.fx.recorded_at)})`] : r.fx.note));
    body.push(h('div', { class: 'card trace' }, trace));
  }
  // آخرین تلاش جدا از آخرین قیمت موفق
  body.push(h('h4', { class: 'section-title' }, 'آخرین تلاش دریافت (جدا از آخرین قیمت موفق)'));
  body.push(r.latest_attempt ? h('div', { class: 'card trace' },
    h('div', null, `منبع: ${r.latest_attempt.provider} — زمان: ${fmtDateTime(r.latest_attempt.at)}`),
    h('div', null, 'نتیجه: ', r.latest_attempt.status === 'ok' ? badge('موفق', 'ok') : badge('ناموفق', 'bad'), r.latest_attempt.error ? ` ${r.latest_attempt.error}` : ''))
    : h('div', { class: 'empty-note' }, 'هنوز دریافتی از منابع خودکار انجام نشده است.'));
  if (r.last_invalid) body.push(notice(`آخرین قیمت دریافتی نامعتبر بود و ذخیره‌شده اما در ارزش‌گذاری استفاده نمی‌شود: ${r.last_invalid.validity_note || ''}`, 'warn'));
  modal({ title: `جزئیات قیمت — ${r.name}`, wide: true, body });
}

async function openPriority(r, onDone) {
  const { providers, kinds } = await loadProviders();
  const ed = sourcesEditor({ providers, kinds, initial: r.sources.map((s) => ({ provider_id: s.provider_id, external_id: s.external_id, price_field: s.price_field, is_enabled: s.is_enabled })), currency: r.currency });
  const err = h('div', { class: 'form-error', role: 'alert', hidden: true });
  const save = h('button', { class: 'btn primary', type: 'button' }, 'ذخیرهٔ اولویت‌ها');
  const m = modal({ title: `اولویت منابع قیمت — ${r.name}`, wide: true, body: [ed.node, err], footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), save] });
  save.addEventListener('click', async () => {
    const v = ed.validate();
    if (v) { err.textContent = v; err.hidden = false; return; }
    save.disabled = true;
    try { await api.put(`/api/assets/${r.asset_id}/price-sources`, ed.get(), { silent: true }); m.close(); toast('اولویت منابع ذخیره شد؛ قیمت‌های ثبت‌شدهٔ قبلی تغییر نکردند.', 'success'); onDone(); }
    catch (e) { err.textContent = e.message; err.hidden = false; save.disabled = false; }
  });
}

async function compareFetch(r, done) {
  try {
    const res = await api.post(`/api/assets/${r.asset_id}/refresh-price?all_sources=true`);
    const okN = res.attempts.filter((a) => a.ok).length;
    toast(`${r.name}: ${res.ok ? `قیمت از ${num(okN)} منبع دریافت شد` : res.message}`, res.ok ? 'success' : 'warn', 7000);
  } catch (e) { /* api خودش پیام را نشان می‌دهد */ }
  done();
}

async function assetsTab(root) {
  const [prov] = await Promise.all([api.get('/api/market-data/providers')]);
  const form = buildForm([
    { name: 'q', label: 'جستجو', type: 'text', placeholder: 'نام یا نماد دارایی' },
    { name: 'status', label: 'وضعیت قیمت', type: 'select', options: [{ value: '', label: 'همه' }, ...Object.entries(PRICE_STATUS).map(([value, [label]]) => ({ value, label }))] },
    { name: 'provider_id', label: 'منبع', type: 'select', options: [{ value: '', label: 'همه' }, ...prov.filter((p) => !p.is_archived).map((p) => ({ value: p.id, label: p.name }))] },
  ], { q: '', status: '', provider_id: '' });
  form.form.className = 'filters filters-3';
  const box = h('div');
  const load = async () => {
    const v = form.getValues();
    clear(box).append(loadingBox());
    let res;
    try { res = await api.get('/api/market-data/intelligence/assets', { q: v.q, status: v.status, provider_id: v.provider_id }, { silent: true }); }
    catch (e) { clear(box).append(notice(`بارگذاری ناموفق بود: ${e.message}`, 'bad'), h('button', { class: 'btn', onclick: load }, icon('refresh'), 'تلاش دوباره')); return; }
    const cnt = {};
    res.items.forEach((x) => { cnt[x.status] = (cnt[x.status] || 0) + 1; });
    clear(box).append(
      h('div', { class: 'chips', style: { marginBottom: '10px' } }, Object.entries(PRICE_STATUS).filter(([k]) => cnt[k]).map(([k, [l]]) => h('span', { class: 'chip' }, `${l}: ${num(cnt[k])}`))),
      h('div', { class: 'card' }, table([
        { label: 'دارایی', render: (r) => [h('b', null, r.name), h('div', { class: 'muted small-text' }, r.symbol ? ltr(r.symbol) : '', r.platform ? ` ${r.platform}` : '')] },
        { label: 'قیمت فعلی', class: 'num', render: (r) => [priceText(r.price, r.currency), r.currency !== 'IRT' && r.price !== null ? h('div', { class: 'muted small-text' }, `واحد: ${r.currency}`) : null] },
        { label: 'منبع', render: (r) => (r.source ? [r.source, ' ', originBadge(r.origin), r.using_fallback ? [' ', badge('جایگزین', 'warn')] : null] : '—') },
        { label: 'زمان به‌روزرسانی', render: (r) => (r.recorded_at ? [fmtDateTime(r.recorded_at), h('div', { class: 'muted small-text' }, ageText(r.age_minutes)), r.delay_seconds !== null ? h('div', { class: 'muted small-text' }, `تأخیر داده: ${delayText(r.delay_seconds)}`) : null] : '—') },
        { label: 'وضعیت', render: (r) => [statusBadge(r.status), r.primary_down ? [' ', badge('منبع اصلی قطع', 'bad')] : null] },
        { label: 'اختلاف منابع', class: 'num', render: (r) => (r.comparison.rows.length > 1 ? badge(`${num(r.comparison.spread_pct, 1)}٪`, r.comparison.conflict ? 'bad' : 'ok') : '—') },
        { label: 'زنجیرهٔ منابع', render: chainView },
        { label: '', render: (r) => h('div', { class: 'intel-actions' },
          h('button', { class: 'btn tiny', onclick: () => openDetails(r) }, 'جزئیات'),
          h('button', { class: 'btn tiny', onclick: () => openPriority(r, load) }, 'اولویت منابع'),
          r.has_sources ? h('button', { class: 'btn tiny', title: 'دریافت از همهٔ منابع برای مقایسه', onclick: () => compareFetch(r, load) }, icon('refresh', 14), 'مقایسه') : null,
          h('button', { class: 'btn tiny', onclick: () => openPriceForm({ asset_id: r.asset_id, onDone: load }) }, 'قیمت دستی')) },
      ], res.items, { empty: 'دارایی‌ای با این فیلتر پیدا نشد.' })));
  };
  form.form.addEventListener('input', () => { clearTimeout(load.t); load.t = setTimeout(load, 250); });
  root.append(form.form, box);
  await load();
}

// ---------------------------------------------------------------- هشدارها
async function alertsTab(root) {
  const res = await api.get('/api/market-data/intelligence/alerts');
  root.append(h('div', { class: 'chips', style: { marginBottom: '12px' } },
    ...Object.entries(SEVERITY).map(([k, [l]]) => h('span', { class: 'chip' }, `${l}: ${num(res.counts[k])}`))));
  const form = buildForm([
    { name: 'severity', label: 'شدت', type: 'select', options: [{ value: '', label: 'همه' }, ...Object.entries(SEVERITY).map(([value, [label]]) => ({ value, label }))] },
    { name: 'type', label: 'نوع هشدار', type: 'select', options: [{ value: '', label: 'همه' }, ...Object.entries(res.type_labels).map(([value, label]) => ({ value, label }))] },
  ], { severity: '', type: '' });
  form.form.className = 'filters filters-3';
  const list = h('div', { class: 'stack-cards' });
  const draw = () => {
    const v = form.getValues();
    const items = res.items.filter((a) => (!v.severity || a.severity === v.severity) && (!v.type || a.type === v.type));
    clear(list);
    if (!items.length) { list.append(h('div', { class: 'card empty-state' }, h('h3', null, res.total ? 'هشداری با این فیلتر نیست' : 'هشدار فعالی وجود ندارد'), h('p', { class: 'muted' }, res.total ? 'فیلتر را تغییر دهید.' : 'هیچ مورد مشکوکی در داده‌های قیمت پیدا نشد. هشدارها از وضعیت واقعی قیمت‌ها و لاگ منابع محاسبه می‌شوند.'))); return; }
    items.forEach((a) => list.append(h('div', { class: `alert ${SEVERITY[a.severity][1]}` }, icon('alert', 18), h('div', { style: { flex: 1, minWidth: 0 } },
      h('b', null, a.title, ' ', badge(res.type_labels[a.type], '')),
      h('div', null, a.message),
      h('div', { class: 'muted small-text' }, a.at ? fmtDateTime(a.at) : '', a.asset ? ` — ${a.asset}` : '', a.provider && a.type !== 'provider_down' ? ` — ${a.provider}` : ''),
      h('div', { class: 'intel-actions', style: { marginTop: '6px' } },
        a.asset_id ? h('button', { class: 'btn tiny', onclick: () => { location.hash = '#/intelligence/assets'; } }, 'پایش دارایی') : null,
        a.asset_id && ['stale_price', 'source_disagreement', 'sharp_change', 'invalid_price'].includes(a.type) ? h('button', { class: 'btn tiny', onclick: () => openPriceForm({ asset_id: a.asset_id, onDone: reload }) }, 'ثبت قیمت دستی') : null,
        a.provider_id && a.type === 'provider_down' ? h('button', { class: 'btn tiny', onclick: () => { location.hash = '#/sources'; } }, 'مدیریت منبع') : null)))));
  };
  form.form.addEventListener('change', draw);
  root.append(form.form, list);
  draw();
}

// ---------------------------------------------------------------- گزارش عملکرد
function perfFilters(prov, assets, initial) {
  const from = dateField('from', '', { required: false }), to = dateField('to', '', { required: false });
  const form = buildForm([
    { name: 'days', label: 'بازه', type: 'select', options: [[7, '۷ روز اخیر'], [14, '۱۴ روز اخیر'], [30, '۳۰ روز اخیر'], [90, '۹۰ روز اخیر']].map(([value, label]) => ({ value, label })) },
    { name: 'provider_id', label: 'منبع', type: 'select', options: [{ value: '', label: 'همه' }, ...prov.map((p) => ({ value: p.id, label: p.name }))] },
    { name: 'asset_id', label: 'دارایی', type: 'select', options: [{ value: '', label: 'همه' }, ...assets.map((a) => ({ value: a.id, label: a.name }))] },
  ], initial);
  form.form.className = 'filters';
  form.form.append(h('label', null, h('span', { class: 'lbl' }, 'از تاریخ'), from), h('label', null, h('span', { class: 'lbl' }, 'تا تاریخ'), to));
  form.dates = () => ({ date_from: from.getValue(), date_to: to.getValue() });
  return form;
}
const multiLine = (labels, datasets, { suffix = '', max, stacked = false, type = 'line' } = {}) => ({
  type,
  data: { labels, datasets },
  options: {
    interaction: { mode: 'index', intersect: false }, spanGaps: true,
    plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y === null ? '—' : num(c.parsed.y, 1)}${suffix}` } } },
    scales: {
      x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, maxRotation: 0, autoSkipPadding: 16 }, stacked },
      y: { position: 'right', beginAtZero: true, max, stacked, grid: { color: COLORS.grid }, ticks: { color: COLORS.text, precision: type === 'bar' ? 0 : undefined, callback: (v) => num(v) + suffix } },
    },
  },
});

async function performanceTab(root) {
  const [prov, assets] = await Promise.all([api.get('/api/market-data/providers'), api.get('/api/assets')]);
  const form = perfFilters(prov.filter((p) => !p.is_archived), assets.assets, { days: 14, provider_id: '', asset_id: '' });
  const box = h('div');
  const load = async () => {
    const v = form.getValues();
    clear(box).append(loadingBox());
    let res;
    try { res = await api.get('/api/market-data/intelligence/performance', { days: v.days, provider_id: v.provider_id, asset_id: v.asset_id, ...form.dates() }, { silent: true }); }
    catch (e) { clear(box).append(notice(`بارگذاری ناموفق بود: ${e.message}`, 'bad'), h('button', { class: 'btn', onclick: load }, icon('refresh'), 'تلاش دوباره')); return; }
    clear(box);
    if (!res.series.length) { box.append(h('div', { class: 'card empty-state' }, h('h3', null, 'درخواستی برای این بازه ثبت نشده است'), h('p', { class: 'muted' }, 'پس از فعال‌کردن یک منبع و دریافت قیمت، نمودارهای عملکرد از لاگ واقعی درخواست‌ها ساخته می‌شود.'))); return; }
    const labels = res.days.map((d) => fmtDate(d).slice(5));
    const sets = (key) => res.series.map((s, i) => ({ label: s.name, data: s.points.map((p) => p[key]), borderColor: PALETTE[i % PALETTE.length], backgroundColor: PALETTE[i % PALETTE.length], tension: 0.25, pointRadius: 2, borderWidth: 2 }));
    box.append(
      h('div', { class: 'grid charts' },
        chartCard('نرخ موفقیت روزانهٔ منابع', () => multiLine(labels, sets('success_rate'), { suffix: '٪', max: 100 }), { sub: 'روزهای بدون درخواست خالی می‌مانند' }),
        chartCard('میانگین زمان پاسخ (میلی‌ثانیه)', () => multiLine(labels, sets('avg_latency_ms')), { sub: 'فقط درخواست‌های موفق' }),
        chartCard('تعداد درخواست‌ها', () => multiLine(labels, sets('requests').map((d) => ({ ...d, backgroundColor: d.borderColor, borderRadius: 4 })), { type: 'bar', stacked: true })),
        chartCard('تعداد خطاها', () => multiLine(labels, sets('errors').map((d) => ({ ...d, backgroundColor: d.borderColor, borderRadius: 4 })), { type: 'bar', stacked: true }))),
      h('h2', { class: 'section-title' }, 'خلاصهٔ هر منبع در بازه'),
      h('div', { class: 'card' }, table([
        { label: 'منبع', render: (s) => h('b', null, s.name) }, { label: 'درخواست', class: 'num', render: (s) => num(s.total.requests) },
        { label: 'موفق', class: 'num', render: (s) => num(s.total.ok) }, { label: 'خطا', class: 'num', render: (s) => num(s.total.errors) },
        { label: 'درصد موفقیت', render: (s) => rateBadge(s.total.success_rate) }, { label: 'میانگین پاسخ', render: (s) => msText(s.total.avg_latency_ms) },
      ], res.series)));
  };
  form.form.addEventListener('change', load);
  root.append(form.form, box);
  await load();
}

// ---------------------------------------------------------------- لاگ‌ها
async function logsTab(root) {
  const [prov, assets] = await Promise.all([api.get('/api/market-data/providers'), api.get('/api/assets')]);
  const from = dateField('from', '', { required: false }), to = dateField('to', '', { required: false });
  const form = buildForm([
    { name: 'provider_id', label: 'منبع', type: 'select', options: [{ value: '', label: 'همه' }, ...prov.filter((p) => !p.is_archived).map((p) => ({ value: p.id, label: p.name }))] },
    { name: 'asset_id', label: 'دارایی', type: 'select', options: [{ value: '', label: 'همه' }, ...assets.assets.map((a) => ({ value: a.id, label: a.name }))] },
    { name: 'status', label: 'نتیجه', type: 'select', options: [{ value: '', label: 'همه' }, ...Object.entries(LOG_STATUS).map(([value, [label]]) => ({ value, label }))] },
  ], { provider_id: '', asset_id: '', status: '' });
  form.form.className = 'filters';
  form.form.append(h('label', null, h('span', { class: 'lbl' }, 'از تاریخ'), from), h('label', null, h('span', { class: 'lbl' }, 'تا تاریخ'), to));
  const box = h('div');
  let page = 1;
  const load = async (reset = true) => {
    if (reset) page = 1;
    const v = form.getValues();
    clear(box).append(loadingBox());
    let res;
    try { res = await api.get('/api/market-data/intelligence/logs', { provider_id: v.provider_id, asset_id: v.asset_id, status: v.status, date_from: from.getValue(), date_to: to.getValue(), page, page_size: 25 }, { silent: true }); }
    catch (e) { clear(box).append(notice(`بارگذاری ناموفق بود: ${e.message}`, 'bad'), h('button', { class: 'btn', onclick: () => load(false) }, icon('refresh'), 'تلاش دوباره')); return; }
    const pages = Math.max(1, Math.ceil(res.total / res.page_size));
    clear(box).append(h('div', { class: 'card' }, table([
      { label: 'زمان', render: (l) => fmtDateTime(l.ts) }, { label: 'منبع', render: (l) => l.provider || '—' }, { label: 'دارایی', render: (l) => l.asset || '—' },
      { label: 'نتیجه', render: (l) => { const [t, k] = LOG_STATUS[l.status] || [l.status, '']; return badge(t, k); } },
      { label: 'زمان پاسخ', render: (l) => msText(l.latency_ms) },
      { label: 'قیمت', class: 'num', render: (l) => (l.price === null || l.price === undefined ? '—' : units(l.price)) },
      { label: 'پیام', render: (l) => h('span', { class: 'small-text', title: l.message }, (l.message || '').slice(0, 120)) },
    ], res.items, { empty: 'لاگی با این فیلتر پیدا نشد.' })),
    h('div', { class: 'pager' }, h('span', null, `${num(res.total)} مورد — صفحهٔ ${num(page)} از ${num(pages)}`),
      h('div', { class: 'btns' },
        h('button', { class: 'btn tiny', disabled: page <= 1, onclick: () => { page -= 1; load(false); } }, 'قبلی'),
        h('button', { class: 'btn tiny', disabled: page >= pages, onclick: () => { page += 1; load(false); } }, 'بعدی'))));
  };
  form.form.addEventListener('change', () => load());
  root.append(form.form, box);
  await load();
}

export async function render(root, rest = []) {
  const tab = TABS.some(([k]) => k === rest[0]) ? rest[0] : 'overview';
  root.append(pageHead('مرکز هوشمندی قیمت‌ها', 'پایش سلامت منابع، کیفیت قیمت‌ها و هشدارهای هوشمند — فقط تحلیل و پیشنهاد؛ هیچ سفارشی ثبت نمی‌شود',
    h('button', { class: 'btn', onclick: reload }, icon('refresh'), 'بازخوانی')), tabs(tab));
  const body = h('div');
  root.append(body);
  if (tab === 'overview') await overviewTab(body, Number(rest[1]) || 7);
  else if (tab === 'assets') await assetsTab(body);
  else if (tab === 'alerts') await alertsTab(body);
  else if (tab === 'performance') await performanceTab(body);
  else await logsTab(body);
}
