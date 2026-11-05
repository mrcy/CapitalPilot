// «بازار جامع ایران» (Iran Market Data): فهرست پویای همهٔ نمادها، سلامت دریافت و جزئیات هر نماد.
// داده فقط توسط Backend دریافت و در دیتابیس نگه‌داری می‌شود؛ مرورگر هرگز مستقیم به منبع وصل نمی‌شود.
// این صفحه فقط نمایش و اتصال تأییدشدهٔ نماد به دارایی را انجام می‌دهد؛ هیچ سفارشی ثبت نمی‌شود.
import { api } from '../api.js';
import { reload } from '../app.js';
import { chartCard, COLORS, lineConfig } from '../charts.js';
import { badge, clear, confirmDialog, h, icon, kpi, loadingBox, modal, notice, pageHead, table, toast } from '../ui.js';
import { pager, toolbar } from '../listkit.js';
import { openSymbolLinker, priceWithCur, symName, symStatusBadge } from '../imlinker.js';
import { CATEGORY_LABEL, CONNECTION, FLAG_LABEL, MARKET_LABEL, SYMBOL_STATUS, currencyLabel, fmtDate, fmtDateTime, num, pnlClass, signedPct, unitName, units } from '../format.js';

const ltr = (t) => h('span', { dir: 'ltr', class: 'ltr-text' }, t);
const TABS = [['', 'نمادها'], ['health', 'دریافت‌ها و سلامت']];
const PAGE_SIZE = 50;
// وضعیت فیلترها بین بازسازی‌های صفحه حفظ می‌شود
const view = { q: '', category: '', market: '', currency: '', status: '', linked: '', sort: 'time:desc', page: 1 };
const SORTS = [['time:desc', 'مرتب‌سازی: جدیدترین قیمت'], ['category:asc', 'دسته'], ['name:asc', 'نام فارسی (الف تا ی)'], ['symbol:asc', 'نماد (A تا Z)'], ['price:desc', 'قیمت (زیاد به کم)'], ['price:asc', 'قیمت (کم به زیاد)'],
  ['change_pct:desc', 'تغییر٪ (بیشترین رشد)'], ['change_pct:asc', 'تغییر٪ (بیشترین افت)']];

const timeAge = (m) => (m === null || m === undefined ? '' : m < 1 ? 'هم‌اکنون' : m < 60 ? `${num(m)} دقیقه پیش` : m < 1440 ? `${num(Math.floor(m / 60))} ساعت پیش` : `${num(Math.floor(m / 1440))} روز پیش`);
const connBadge = (c) => { const [t, k] = CONNECTION[c] || [c, '']; return badge(t, k); };

function tabsNav(active) {
  return h('nav', { class: 'tabs', 'aria-label': 'بخش‌های بازار جامع ایران' }, TABS.map(([k, label]) => h('a', { class: `tab ${k === active ? 'active' : ''}`, href: `#/iran-market${k ? `/${k}` : ''}`, 'aria-current': k === active ? 'page' : null }, label)));
}

async function enableProvider(ov) {
  await api.post(`/api/market-data/providers/${ov.provider.id}/enable?enabled=true`);
  toast('منبع Iran Market Data فعال شد. اکنون می‌توانید دریافت دستی بزنید.', 'success');
  reload();
}

async function manualFetch(btn) {
  btn.disabled = true;
  try {
    const r = await api.post('/api/iran-market/refresh');
    toast(r.message || (r.ok ? 'دریافت انجام شد.' : 'دریافت ناموفق بود.'), r.status === 'ok' || r.status === 'unchanged' ? 'success' : r.status === 'skipped' ? 'info' : 'warn', 7000);
  } catch (e) { /* api.js خطا را نمایش داده است */ }
  reload();
}

function headerActions(ov) {
  const p = ov.provider;
  return [
    p && !p.is_enabled ? h('button', { class: 'btn primary', 'data-testid': 'im-enable', onclick: () => enableProvider(ov) }, icon('check', 15), 'فعال‌سازی منبع') : null,
    p && p.is_enabled ? h('button', { class: 'btn primary', 'data-testid': 'im-refresh', onclick: (e) => manualFetch(e.currentTarget) }, icon('refresh', 15), 'دریافت دستی') : null,
    h('a', { class: 'btn', href: '#/sources' }, icon('sources', 15), 'تنظیم منبع'),
  ];
}

function statusBanner(ov) {
  const s = ov.snapshot;
  if (!ov.provider) return notice('منبع Iran Market Data بایگانی یا حذف شده است؛ از صفحهٔ «منابع قیمت» بازیابی یا دوباره بسازید.', 'bad');
  if (ov.connection === 'disabled') return h('div', { class: 'card empty-state', 'data-testid': 'im-disabled' }, h('h3', null, 'منبع Iran Market Data غیرفعال است'),
    h('p', { class: 'muted' }, s.has_data ? 'آخرین داده‌های ذخیره‌شده نمایش داده می‌شود ولی به‌روز نمی‌شود و برای ارزش‌گذاری به‌عنوان «قدیمی» حساب می‌شود.' : 'هنوز هیچ دریافتی انجام نشده است. با فعال‌سازی، Backend فایل عمومی همهٔ نمادها را (هر ۳۰ دقیقه) دریافت و در دیتابیس نگه می‌دارد.'),
    h('button', { class: 'btn primary', onclick: () => enableProvider(ov) }, icon('check', 15), 'فعال‌سازی منبع'));
  if (!s.has_data) return notice(`هنوز داده‌ای دریافت نشده است. «دریافت دستی» را بزنید.${s.last_error ? ` آخرین خطا: ${s.last_error}` : ''}`, s.last_error ? 'bad' : 'warn');
  if (ov.connection === 'error') return notice(`دریافت آخر ناموفق بود (${s.last_error}). داده‌های ${timeAge(s.fetch_age_minutes)} نگه داشته شده‌اند و ${s.stale ? 'اکنون قدیمی حساب می‌شوند' : 'تا قدیمی‌شدن معتبر می‌مانند'}.`, 'bad');
  if (s.stale) return notice(`داده‌ها قدیمی هستند: ${s.reason} قیمت‌ها زنده نیستند و در ارزش‌گذاری استفاده نمی‌شوند.`, 'warn');
  return null;
}

function overviewKpis(ov) {
  const t = ov.totals, s = ov.snapshot;
  return h('div', { class: 'grid kpis k7', 'data-testid': 'im-kpis' },
    kpi({ label: 'تعداد نمادها', value: num(t.total), sub: `${num(t.linked_assets)} دارایی متصل`, tone: 'blue' }),
    kpi({ label: 'قیمت معتبر', value: num(t.valid), sub: t.warning ? `${num(t.warning)} با هشدار کیفیت` : 'قابل استفاده در ارزش‌گذاری', tone: 'green' }),
    kpi({ label: 'قیمت قدیمی', value: num(t.stale), sub: 'در ارزش‌گذاری نمی‌آید', tone: t.stale ? 'gold' : '' }),
    kpi({ label: 'بدون قیمت / نامعتبر', value: `${num(t.no_price)} / ${num(t.invalid)}`, sub: 'قیمت خالی یا ردشده', tone: t.invalid ? 'red' : '' }),
    kpi({ label: 'تعداد دسته‌ها', value: num(t.categories), sub: 'استخراج‌شده از خود فایل', tone: 'accent' }),
    kpi({ label: 'زمان تولید فایل', value: h('span', { class: 'kpi-small' }, s.generated_at ? fmtDateTime(s.generated_at) : '—'), sub: s.last_ok_at ? `آخرین دریافت: ${fmtDateTime(s.last_ok_at)}` : 'دریافت نشده', tone: 'blue' }),
    kpi({ label: 'وضعیت اتصال API', value: connBadge(ov.connection), sub: ov.requests.last_24h ? `${num(ov.requests.last_24h)} دریافت و ${num(ov.requests.errors_24h)} خطا در ۲۴ ساعت` : 'بدون دریافت اخیر', tone: ov.connection === 'ok' ? 'green' : ov.connection === 'error' ? 'red' : '' }));
}

function categoryChips(ov, onPick) {
  const mk = (key, label, count) => h('button', { type: 'button', class: `tab ${view.category === key ? 'active' : ''}`, 'data-cat': key, onclick: () => onPick(key) }, `${label} (${num(count)})`);
  return h('div', { class: 'chips im-cats', role: 'group', 'aria-label': 'دسته‌ها' }, mk('', 'همه', ov.totals.total), ov.categories.map((c) => mk(c.key, CATEGORY_LABEL[c.key], c.count)));
}

const optList = (first, items, labeler) => [{ value: '', label: first }, ...items.map((i) => ({ value: i.key, label: `${labeler(i.key)} (${num(i.count)})` }))];

function symbolsTable(items) {
  return table([
    { label: 'نام', render: (s) => {
      const fa = s.name_fa && s.name_fa !== s.symbol ? s.name_fa : '', en = s.name_en && s.name_en !== s.symbol ? s.name_en : '';
      return h('div', null, h('a', { href: `#/iran-market/s/${encodeURIComponent(s.symbol)}`, class: 'im-name' }, fa || en || 'بدون نام'),
        fa && en ? h('div', { class: 'muted', dir: 'ltr', style: { fontSize: '12px', textAlign: 'right' } }, en) : null);
    } },
    { label: 'نماد', render: (s) => ltr(s.symbol) },
    { label: 'دسته', render: (s) => CATEGORY_LABEL[s.category] },
    { label: 'بازار', render: (s) => MARKET_LABEL[s.market] },
    { label: 'قیمت', class: 'num', render: (s) => (s.price === null ? '—' : h('b', { class: s.status === 'valid' || s.status === 'warning' ? '' : 'muted' }, s.currency === 'IRT' ? num(s.price, 2) : units(s.price))) },
    { label: 'ارز', render: (s) => currencyLabel(s.currency) },
    { label: 'واحد', render: (s) => `${unitName(s.unit)}${Number(s.unit_size) !== 1 ? ` ×${num(s.unit_size)}` : ''}` },
    { label: 'تغییر٪', class: 'num', render: (s) => h('span', { class: pnlClass(s.change_pct) }, signedPct(s.change_pct)) },
    { label: 'باز / بالا / پایین', class: 'num', render: (s) => (s.open === null && s.high === null && s.low === null ? '—' : h('div', { class: 'im-ohlc' }, h('span', null, units(s.open)), h('span', null, units(s.high)), h('span', null, units(s.low)))) },
    { label: 'آخرین تغییر قیمت', render: (s) => h('div', null, s.price_time ? fmtDateTime(s.price_time) : '—', h('div', { class: 'muted', style: { fontSize: '11.5px' } }, timeAge(s.age_minutes))) },
    { label: 'منبع اصلی', render: (s) => s.source || '—' },
    { label: 'وضعیت', render: (s) => h('div', null, symStatusBadge(s.status), s.linked_count ? h('div', null, badge(`متصل به ${num(s.linked_count)} دارایی`, 'blue')) : null) },
  ], items, { empty: 'نمادی با این فیلترها پیدا نشد.', compact: true });
}

async function listTab(root, ov) {
  const body = h('div');
  const draw = async () => {
    const [sort, order] = view.sort.split(':');
    clear(body).append(loadingBox());
    const r = await api.get('/api/iran-market/symbols', { q: view.q, category: view.category, market: view.market, currency: view.currency, status: view.status, linked: view.linked, sort, order, page: view.page, page_size: PAGE_SIZE });
    clear(body).append(h('div', { class: 'card im-table', 'data-testid': 'im-table' }, symbolsTable(r.items)), pager({ page: r.page, pageSize: r.page_size, total: r.total, onPage: (p) => { view.page = p; draw(); window.scrollTo({ top: 0 }); } }));
  };
  if (ov.totals.total) {
    root.append(categoryChips(ov, (k) => { view.category = k; view.page = 1; root.querySelectorAll('.im-cats .tab').forEach((b) => b.classList.toggle('active', b.dataset.cat === k)); draw(); }));
    root.append(toolbar({ placeholder: 'جستجو در نام فارسی، نام انگلیسی یا نماد…', q: view.q, filters: [
      { name: 'market', label: 'بازار', value: view.market, options: optList('همهٔ بازارها', ov.facets.markets, (k) => MARKET_LABEL[k]) },
      { name: 'currency', label: 'ارز', value: view.currency, options: optList('همهٔ ارزها', ov.facets.currencies, currencyLabel) },
      { name: 'status', label: 'وضعیت', value: view.status, options: [{ value: '', label: 'همهٔ وضعیت‌ها' }, ...Object.entries(SYMBOL_STATUS).map(([value, [label]]) => ({ value, label }))] },
      { name: 'linked', label: 'اتصال', value: view.linked, options: [{ value: '', label: 'متصل و غیرمتصل' }, { value: 'true', label: 'فقط متصل به دارایی' }] },
      { name: 'sort', label: 'مرتب‌سازی', value: view.sort, options: SORTS.map(([value, label]) => ({ value, label })) },
    ], onChange: (v) => { Object.assign(view, v, { page: 1 }); draw(); } }));
    root.append(h('p', { class: 'muted im-hint' }, 'قیمت‌ها با ارز و واحد خودشان نمایش داده می‌شوند و بدون تبدیل واحد قابل مقایسه نیستند؛ برای مرتب‌سازی معنادار، ارز یا دسته را فیلتر کنید.'));
    root.append(body);
    await draw();
  } else if (ov.provider?.is_enabled) {
    root.append(h('div', { class: 'card empty-state' }, h('h3', null, 'هنوز نمادی دریافت نشده است'), h('p', { class: 'muted' }, 'با «دریافت دستی» فایل از منبع گرفته می‌شود؛ پس از آن زمان‌بند هر ۳۰ دقیقه خودکار به‌روز می‌کند.')));
  }
}

// ---------------------------------------------------------------- سلامت و تاریخچهٔ دریافت‌ها
const SNAP_STATUS = { ok: ['موفق', 'ok'], unchanged: ['بدون تغییر', ''], error: ['خطا', 'bad'] };
async function healthTab(root, ov) {
  const s = ov.snapshot, p = ov.provider, rq = ov.requests;
  const snaps = (await api.get('/api/iran-market/snapshots', { limit: 40 })).items;
  const kv = (l, v) => h('div', null, h('span', null, l), h('b', null, v ?? '—'));
  root.append(h('div', { class: 'card', 'data-testid': 'im-health' }, h('h3', null, 'سلامت اتصال ', connBadge(ov.connection)),
    h('div', { class: 'kv kv-3' },
      kv('آخرین دریافت موفق', s.last_ok_at ? `${fmtDateTime(s.last_ok_at)} (${timeAge(s.fetch_age_minutes)})` : '—'),
      kv('زمان تولید فایل در منبع', s.generated_at ? `${fmtDateTime(s.generated_at)} (${timeAge(s.file_age_minutes)})` : '—'),
      kv('آخرین تلاش', s.last_attempt_at ? fmtDateTime(s.last_attempt_at) : '—'),
      kv('بازهٔ دریافت خودکار', p ? `${num(p.interval_minutes)} دقیقه` : '—'),
      kv('تعداد نمادها / دسته‌ها', `${num(ov.totals.total)} / ${num(ov.totals.categories)}`),
      kv('نمادهای قدیمی', num(ov.totals.stale)),
      kv('زمان پاسخ آخرین دریافت', s.latency_ms != null ? `${num(s.latency_ms)} میلی‌ثانیه` : '—'),
      kv('میانگین زمان پاسخ (۲۴ ساعت)', rq.avg_latency_ms != null ? `${num(rq.avg_latency_ms)} میلی‌ثانیه` : '—'),
      kv('درخواست‌ها / خطاها (۲۴ ساعت)', `${num(rq.last_24h)} / ${num(rq.errors_24h)}`),
      kv('حجم فایل', s.size_bytes ? `${num(Math.round(s.size_bytes / 1024))} کیلوبایت` : '—'),
      kv('آستانهٔ قدیمی‌شدن داده', `${num(s.stale_after_minutes)} دقیقه`),
      kv('منابع اصلی قیمت در فایل', s.upstream_sources || '—')),
    s.last_error ? notice(`آخرین خطا: ${s.last_error}`, 'bad') : null,
    h('div', { class: 'intel-actions', style: { marginTop: '10px' } },
      p?.is_enabled ? h('button', { class: 'btn primary', onclick: (e) => manualFetch(e.currentTarget) }, icon('refresh', 15), 'دریافت دستی') : (p ? h('button', { class: 'btn primary', onclick: () => enableProvider(ov) }, 'فعال‌سازی منبع') : null),
      h('a', { class: 'btn', href: '#/sources' }, icon('sources', 15), 'تنظیمات منبع'))));
  root.append(h('h2', { class: 'section-title' }, 'تاریخچهٔ دریافت‌ها', h('small', null, 'پاسخ خام فقط برای چند دریافت آخر نگه‌داری می‌شود')));
  root.append(h('div', { class: 'card' }, table([
    { label: 'زمان دریافت', render: (x) => fmtDateTime(x.fetched_at) },
    { label: 'وضعیت', render: (x) => { const [t, k] = SNAP_STATUS[x.status] || [x.status, '']; return badge(t, k); } },
    { label: 'زمان تولید فایل', render: (x) => (x.generated_at ? fmtDateTime(x.generated_at) : '—') },
    { label: 'HTTP', class: 'num', render: (x) => (x.http_status ? ltr(String(x.http_status)) : '—') },
    { label: 'زمان پاسخ', class: 'num', render: (x) => (x.latency_ms != null ? `${num(x.latency_ms)} میلی‌ثانیه` : '—') },
    { label: 'نماد', class: 'num', render: (x) => num(x.symbol_count) },
    { label: 'تغییرکرده', class: 'num', render: (x) => num(x.changed_count) },
    { label: 'معتبر / قدیمی', class: 'num', render: (x) => `${num(x.valid_count)} / ${num(x.stale_count)}` },
    { label: 'پیام', render: (x) => x.error || '—' },
    { label: 'پاسخ خام', render: (x) => (x.has_raw ? h('a', { class: 'btn tiny', href: `/api/iran-market/snapshots/${x.id}/raw`, download: `iranmarket-${x.id}.json` }, icon('download', 13), 'دانلود') : '—') },
  ], snaps, { empty: 'هنوز دریافتی ثبت نشده است.', compact: true })));
}

// ---------------------------------------------------------------- جزئیات نماد
function openAssetLink(d, onDone) {
  api.get('/api/assets', { status: 'active' }, { silent: true }).then((assets) => {
    const list = (assets.assets || assets.items || (Array.isArray(assets) ? assets : [])).filter((a) => !a.is_archived);
    const sel = h('select', { 'aria-label': 'دارایی', 'data-testid': 'im-asset-select' }, list.map((a) => h('option', { value: a.id }, `${a.name} (${a.price_currency})`)));
    const pick = () => list.find((a) => String(a.id) === sel.value);
    const out = h('div');
    const go = h('button', { class: 'btn primary', type: 'button', onclick: () => {
      const a = pick();
      if (!a) return;
      m.close();
      openSymbolLinker({ asset: a, currency: a.price_currency, current: d.symbol, onConfirm: async (picked) => {
        if (picked.symbol !== d.symbol) { /* کاربر نماد دیگری انتخاب کرد */ }
        try { await api.post('/api/iran-market/link', { asset_id: a.id, symbol: picked.symbol, confirm: true }); toast(`«${a.name}» به نماد ${picked.symbol} وصل شد.`, 'success'); onDone(); } catch (e) { /* toast */ }
      } });
    } }, icon('link', 15), 'ادامه و تأیید');
    const m = modal({ title: `اتصال نماد ${d.symbol} به یک دارایی`, body: [h('p', { class: 'muted', style: { marginTop: 0 } }, 'یک دارایی موجود را انتخاب کنید؛ در مرحلهٔ بعد قیمت و واحد را می‌بینید و صراحتاً تأیید می‌کنید. دارایی جدیدی ساخته نمی‌شود.'),
      list.length ? h('label', null, h('span', { class: 'lbl' }, 'دارایی'), sel) : notice('دارایی فعالی وجود ندارد؛ ابتدا در «دارایی‌ها» یک دارایی بسازید.', 'info'), out], footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), list.length ? go : null] });
  });
}

async function detailPage(root, symbol) {
  const d = await api.get(`/api/iran-market/symbols/${encodeURIComponent(symbol)}`);
  const kv = (l, v) => h('div', null, h('span', null, l), h('b', null, v ?? '—'));
  const num2 = (v) => (v === null || v === undefined ? '—' : d.currency === 'IRT' ? num(v, 2) : units(v));
  root.append(pageHead(symName(d), d.name_en && d.name_en !== d.symbol ? d.name_en : '', h('a', { class: 'btn', href: '#/iran-market' }, icon('back', 15), 'بازگشت به فهرست'),
    h('button', { class: 'btn primary', 'data-testid': 'im-link-asset', onclick: () => openAssetLink(d, () => reload()) }, icon('link', 15), 'اتصال به دارایی')));
  root.append(h('div', { class: 'grid kpis k6', 'data-testid': 'im-detail' },
    kpi({ label: 'آخرین قیمت', value: priceWithCur(d.price, d.currency), sub: `برای هر ${unitName(d.unit)}${Number(d.unit_size) !== 1 ? ` ×${num(d.unit_size)}` : ''}`, tone: d.status === 'valid' ? 'green' : 'gold' }),
    kpi({ label: 'تغییر روزانه', value: h('span', { class: pnlClass(d.change_pct) }, signedPct(d.change_pct)), sub: d.change !== null ? `${num2(d.change)} ${currencyLabel(d.currency)}` : '' }),
    kpi({ label: 'وضعیت قیمت', value: symStatusBadge(d.status), sub: d.status_reason || 'قابل استفاده در ارزش‌گذاری' }),
    kpi({ label: 'منبع اصلی', value: d.source || '—', sub: d.market_status ? `بازار: ${d.market_status}` : '' }),
    kpi({ label: 'زمان قیمت', value: h('span', { class: 'kpi-small' }, d.price_time ? fmtDateTime(d.price_time) : '—'), sub: timeAge(d.age_minutes) }),
    kpi({ label: 'زمان بررسی منبع', value: h('span', { class: 'kpi-small' }, d.checked_at ? fmtDateTime(d.checked_at) : '—'), sub: 'checked_at؛ جدا از زمان قیمت' })));
  if (d.status !== 'valid' && d.status !== 'warning') root.append(notice(`این قیمت در ارزش‌گذاری استفاده نمی‌شود: ${d.status_reason}`, d.status === 'stale' ? 'warn' : 'bad'));
  if (d.quality.length) root.append(notice(`هشدار کیفیت منبع: ${d.quality.map((f) => FLAG_LABEL[`api_${f}`] || f).join('، ')}`, 'warn'));
  d.link_blockers.forEach((b) => root.append(notice(`اتصال به دارایی ممکن نیست: ${b}`, 'info')));
  root.append(h('div', { class: 'card' }, h('h3', null, 'مشخصات نماد'), h('div', { class: 'kv kv-3' },
    kv('نماد', ltr(d.symbol)), kv('دسته', CATEGORY_LABEL[d.category]), kv('بازار', MARKET_LABEL[d.market]), kv('واحد پول', `${currencyLabel(d.currency)}${d.currency ? ` (${d.currency})` : ''}`),
    kv('واحد قیمت', `${unitName(d.unit)} (اندازه ${num(d.unit_size)})`), kv('حجم', d.volume != null ? num(d.volume) : '—'),
    kv('باز', num2(d.open)), kv('بالا', num2(d.high)), kv('پایین', num2(d.low)), kv('قیمت پایانی قبل', num2(d.prev_close)), kv('خرید (bid)', num2(d.bid)), kv('فروش (ask)', num2(d.ask)),
    kv('زمان قیمت (جلالی)', d.timestamp_jalali || '—'), kv('زمان قیمت (UTC)', d.timestamp ? ltr(d.timestamp) : '—'), kv('آخرین مشاهده در فایل', d.last_seen_at ? fmtDateTime(d.last_seen_at) : '—'))));
  // نمودار تاریخچه: مسیر مستند API؛ اگر نبود، فقط قیمت‌های ذخیره‌شدهٔ خود CapitalPilot
  const histBox = h('div');
  root.append(histBox);
  const [hist, stored] = await Promise.all([api.get(`/api/iran-market/symbols/${encodeURIComponent(symbol)}/history`, { days: 180 }), api.get(`/api/iran-market/symbols/${encodeURIComponent(symbol)}/stored-prices`)]);
  if (hist.available && hist.points.length) {
    const pts = hist.points.map((x) => ({ date: String(x.t).slice(0, 10), close: x.close }));
    histBox.append(chartCard(`تاریخچهٔ روزانه (${num(hist.points.length)} روز آخر، ${currencyLabel(hist.currency || d.currency)})`, () => lineConfig(pts, [{ key: 'close', label: 'قیمت پایانی', color: COLORS.blue, fill: 'rgba(74,163,255,.10)' }]), { sub: 'منبع: فایل‌های تاریخچهٔ منتشرشدهٔ Iran Market Data؛ در دیتابیس CapitalPilot ذخیره نمی‌شود', tall: true }));
  } else {
    histBox.append(notice(hist.message || 'تاریخچه‌ای در دسترس نیست.', 'info'));
    if (stored.items.length > 1) {
      const pts = [...stored.items].reverse().map((x) => ({ date: x.recorded_at, price: x.price }));
      histBox.append(chartCard('قیمت‌های ذخیره‌شده در CapitalPilot', () => lineConfig(pts, [{ key: 'price', label: 'قیمت', color: COLORS.gold }]), { tall: true }));
    }
  }
  root.append(h('h2', { class: 'section-title' }, 'دارایی‌هایی که از این نماد استفاده می‌کنند'));
  root.append(h('div', { class: 'card', 'data-testid': 'im-linked' }, table([
    { label: 'دارایی', render: (a) => h('a', { href: '#/assets' }, a.name) },
    { label: 'اولویت', class: 'num', render: (a) => num(a.priority) },
    { label: 'واحد دارایی', render: (a) => a.price_currency },
    { label: 'قیمت فعلی دارایی', class: 'num', render: (a) => (a.price === null ? '—' : num(a.price, 2)) },
    { label: 'وضعیت', render: (a) => badge({ valid: 'معتبر', manual: 'دستی', stale: 'قدیمی', invalid: 'نامعتبر', pending: 'در انتظار', conflict: 'اختلاف منابع', missing: 'ناموجود' }[a.price_status] || a.price_status, a.price_status === 'valid' ? 'ok' : 'warn') },
    { label: 'اتصال', render: (a) => h('button', { class: 'btn tiny danger', onclick: async () => { if (await confirmDialog({ message: `اتصال «${a.name}» به ${d.symbol} قطع شود؟ قیمت‌ها و تراکنش‌های ثبت‌شده تغییری نمی‌کنند.`, confirmLabel: 'قطع اتصال', danger: true })) { await api.del(`/api/iran-market/link?asset_id=${a.asset_id}`); toast('اتصال قطع شد.', 'success'); reload(); } } }, 'قطع اتصال') },
  ], d.linked_assets, { empty: 'هنوز هیچ دارایی‌ای به این نماد وصل نیست. نمادها فقط با تأیید صریح شما به دارایی وصل می‌شوند.' })));
  if (stored.items.length) {
    root.append(h('h2', { class: 'section-title' }, 'قیمت‌های ذخیره‌شده در CapitalPilot', h('small', null, 'فقط برای دارایی‌های متصل')));
    root.append(h('div', { class: 'card' }, table([
      { label: 'دارایی', render: (x) => x.asset }, { label: 'قیمت', class: 'num', render: (x) => priceWithCur(x.price, x.currency) },
      { label: 'زمان قیمت', render: (x) => fmtDateTime(x.recorded_at) }, { label: 'زمان بررسی منبع', render: (x) => (x.checked_at ? fmtDateTime(x.checked_at) : '—') },
      { label: 'وضعیت', render: (x) => badge(x.is_valid ? 'معتبر' : 'نامعتبر', x.is_valid ? 'ok' : 'bad') },
    ], stored.items.slice(0, 20), { compact: true })));
  }
}

export async function render(root, rest = []) {
  if (rest[0] === 's' && rest[1]) return detailPage(root, decodeURIComponent(rest.slice(1).join('/')));
  const tab = rest[0] === 'health' ? 'health' : '';
  const ov = await api.get('/api/iran-market/overview');
  root.append(pageHead('بازار جامع ایران', 'همهٔ نمادهای فایل عمومی Iran Market Data: ارز، طلا، سکه، رمزارز، کالا، انرژی و شاخص‌ها — با وضعیت اعتبار مستقل برای هر نماد.', ...headerActions(ov)));
  const banner = statusBanner(ov);
  if (banner) root.append(banner);
  root.append(overviewKpis(ov));
  root.append(h('div', { style: { height: '10px' } }), tabsNav(tab));
  if (tab === 'health') await healthTab(root, ov); else await listTab(root, ov);
  root.append(notice('داده‌ها متعلق به منبع‌های اصلی هستند، صرفاً اطلاع‌رسانی‌اند و توصیهٔ مالی نیستند. هیچ سفارش خرید یا فروشی ثبت نمی‌شود و نمادها بدون تأیید شما به هیچ دارایی وصل نمی‌شوند.', 'info'));
}
