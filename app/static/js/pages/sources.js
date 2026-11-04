import { api } from '../api.js';
import { state } from '../state.js';
import { reload, reloadAll } from '../app.js';
import { badge, clear, confirmDialog, formModal, h, icon, modal, notice, pageHead, toast } from '../ui.js';
import { fmtDateTime, money, num, PROVIDER_STATUS, units } from '../format.js';
import { depList, purgeFlow } from '../listkit.js';
import { openSymbolSearch } from '../sourceseditor.js';

const AUTH = { none: 'بدون احراز هویت', bearer: 'Bearer Token (هدر Authorization)', header: 'هدر سفارشی', query: 'پارامتر کوئری' };
const MARKET = { none: 'بدون تقویم (همیشه)', tse: 'بورس تهران (شنبه تا چهارشنبه، ساعات معاملات)', '24h': '۲۴ ساعته' };
const FIELD_PATHS = [['price', 'مسیر JSON قیمت (الزامی)', '$.data.price'], ['time', 'مسیر JSON زمان قیمت', '$.data.updated'], ['currency', 'مسیر JSON واحد پول', '$.data.currency'], ['change', 'مسیر JSON تغییر ۲۴ساعته', '$.data.change']];

const linesToObj = (t) => Object.fromEntries((t || '').split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf('='); return i < 0 ? [l, ''] : [l.slice(0, i).trim(), l.slice(i + 1).trim()]; }).filter(([k]) => k));
const objToLines = (o) => Object.entries(o || {}).map(([k, v]) => `${k}=${v}`).join('\n');

function openProviderForm({ provider = null, kinds, onDone }) {
  const custom = (k) => ['custom_api', 'streamdata', 'servix'].includes(k);
  const kindOpts = kinds.map((k) => ({ value: k.kind, label: k.label }));
  const codes = [...new Set(['IRR', ...state.meta.currencies.map((c) => c.code)])];
  const cfg = provider?.config || {};
  const fm = provider?.field_map || {};
  const fields = [
    { name: 'name', label: 'نام منبع', type: 'text', required: true },
    { name: 'kind', label: 'نوع منبع', type: 'select', options: kindOpts, hint: provider ? 'نوع پس از ساخت قابل تغییر نیست.' : undefined },
    { type: 'section', name: 'sc', label: 'اتصال' },
    { ltr: true, name: 'base_url', label: 'آدرس API', type: 'text', wide: true, placeholder: 'https://api.example.com/v1/quote/{symbol}', show: (x) => x.kind !== 'manual',
      hint: 'برای TSETMC و بیت‌پین خالی بگذارید تا آدرس پیش‌فرض (متغیر محیطی) استفاده شود. {symbol} با شناسهٔ دارایی جایگزین می‌شود.' },
    { name: 'auth_type', label: 'نوع احراز هویت', type: 'select', options: Object.entries(AUTH).map(([value, label]) => ({ value, label })), show: (x) => custom(x.kind) },
    { ltr: true, name: 'auth_param_name', label: 'نام هدر / پارامتر کلید', type: 'text', placeholder: 'X-API-KEY', show: (x) => custom(x.kind) && ['header', 'query'].includes(x.auth_type) },
    { ltr: true, name: 'api_key', label: 'کلید API', type: 'text', inputType: 'password', wide: true, show: (x) => custom(x.kind) && x.auth_type !== 'none',
      placeholder: provider?.has_api_key ? 'کلید ذخیره شده است؛ برای تغییر کلید جدید را وارد کنید' : 'کلید را وارد کنید',
      hint: 'کلید فقط در سرور و رمزنگاری‌شده نگهداری می‌شود و هرگز در مرورگر نمایش داده نمی‌شود.' },
    ...(provider?.has_api_key ? [{ name: 'clear_api_key', label: 'کلید ذخیره‌شده حذف شود', type: 'checkbox', show: (x) => custom(x.kind) }] : []),
    { ltr: true, name: 'request_params', label: 'پارامترهای درخواست (هر خط key=value)', type: 'textarea', wide: true, show: (x) => custom(x.kind), placeholder: 'symbol={symbol}\nformat=json' },
    { type: 'section', name: 'sf', label: 'استخراج قیمت از پاسخ JSON' },
    ...FIELD_PATHS.map(([k, label, ph]) => ({ ltr: true, name: `fm_${k}`, label, type: 'text', placeholder: ph, show: (x) => custom(x.kind), required: false })),
    { ltr: true, name: 'cfg_multiplier', label: 'ضریب مقدار دریافتی', type: 'decimal', show: (x) => custom(x.kind), hint: 'مثلاً ۰٫۱ برای تبدیل ریال به تومان. خالی = ۱' },
    { ltr: true, name: 'cfg_time_format', label: 'قالب زمان پاسخ', type: 'text', show: (x) => custom(x.kind), placeholder: 'iso | unix | unix_ms | %Y-%m-%d %H:%M:%S' },
    { ltr: true, name: 'cfg_path', label: 'مسیر نسبی endpoint (اختیاری)', type: 'text', show: (x) => custom(x.kind), placeholder: '/quote/{symbol}' },
    { ltr: true, name: 'cfg_sample_symbol', label: 'نماد نمونه برای تست اتصال', type: 'text', show: (x) => custom(x.kind) },
    { ltr: true, name: 'cfg_health_path', label: 'مسیر بررسی سلامت (اختیاری)', type: 'text', show: (x) => custom(x.kind) },
    { ltr: true, name: 'cfg_history_path', label: 'مسیر تاریخچه (اختیاری)', type: 'text', show: (x) => custom(x.kind), placeholder: '/history/{symbol}?from={start}&to={end}' },
    { type: 'section', name: 'sp', label: 'ارز، زمان‌بندی و کنترل درخواست' },
    { name: 'input_currency', label: 'واحد پول قیمت دریافتی', type: 'select', options: codes.map((c) => ({ value: c, label: c === 'IRR' ? 'ریال (IRR)' : `${state.meta.currencies.find((x) => x.code === c)?.name || c} (${c})` })), show: (x) => x.kind !== 'manual' },
    { name: 'market', label: 'تقویم بازار', type: 'select', options: Object.entries(MARKET).map(([value, label]) => ({ value, label })), show: (x) => x.kind !== 'manual' },
    { name: 'refresh_interval_minutes', label: 'بازهٔ به‌روزرسانی (دقیقه)', type: 'int', required: true, show: (x) => x.kind !== 'manual' },
    { name: 'min_interval_seconds', label: 'حداقل فاصلهٔ دو درخواست (ثانیه)', type: 'decimal', show: (x) => x.kind !== 'manual', hint: 'سقف نرخ درخواست' },
    { name: 'retry_count', label: 'تعداد تلاش مجدد', type: 'int', show: (x) => x.kind !== 'manual' },
    { name: 'retry_delay_seconds', label: 'تأخیر پایهٔ تلاش مجدد (ثانیه)', type: 'decimal', show: (x) => x.kind !== 'manual', hint: 'با هر تلاش دو برابر می‌شود.' },
    { name: 'timeout_seconds', label: 'مهلت پاسخ (ثانیه)', type: 'decimal', show: (x) => x.kind !== 'manual' },
    { name: 'auto_approve', label: 'قیمت‌های معتبر خودکار تأیید شوند', type: 'checkbox', wide: true, show: (x) => x.kind !== 'manual', hint: 'اگر خاموش باشد قیمت تا تأیید دستی در ارزش‌گذاری استفاده نمی‌شود.' },
    { name: 'is_enabled', label: 'منبع فعال است', type: 'checkbox', wide: true },
  ];
  const first = kinds.find((k) => k.kind === (provider?.kind || 'custom_api')) || kinds[0];
  const values = provider
    ? { ...provider, request_params: objToLines(provider.request_params), api_key: '', fm_price: fm.price || '', fm_time: fm.time || '', fm_currency: fm.currency || '', fm_change: fm.change || '',
        cfg_multiplier: cfg.multiplier ?? '', cfg_time_format: cfg.time_format || '', cfg_path: cfg.path || '', cfg_sample_symbol: cfg.sample_symbol || '', cfg_health_path: cfg.health_path || '', cfg_history_path: cfg.history_path || '' }
    : { kind: first.kind, auth_type: 'none', input_currency: first.default_unit || 'IRT', market: first.default_market || 'none', refresh_interval_minutes: first.defaults?.refresh_interval_minutes || 30,
        min_interval_seconds: '1', retry_count: 2, retry_delay_seconds: '2', timeout_seconds: '8', auto_approve: !!first.defaults?.auto_approve, is_enabled: false };
  let lastKind = values.kind;
  const f = formModal({
    title: provider ? `ویرایش منبع «${provider.name}»` : 'منبع قیمت جدید', fields, values, wide: true, submitLabel: 'ذخیره منبع',
    extra: h('div', { id: 'kind-desc' }),
    onChange: (x, api2) => {
      const k = kinds.find((y) => y.kind === x.kind);
      const d = document.getElementById('kind-desc');
      if (d && k) { clear(d).append(notice(k.description, 'info')); }
      if (!provider && x.kind !== lastKind && k) {
        lastKind = x.kind;
        api2.setValue('input_currency', k.default_unit || 'IRT'); api2.setValue('market', k.default_market || 'none');
        api2.setValue('refresh_interval_minutes', k.defaults?.refresh_interval_minutes || 30); api2.setValue('auto_approve', !!k.defaults?.auto_approve);
      }
    },
    onSubmit: async (x, m) => {
      const config = {};
      for (const k of ['multiplier', 'time_format', 'path', 'sample_symbol', 'health_path', 'history_path']) { const v = x[`cfg_${k}`]; if (v !== null && v !== undefined && String(v).trim() !== '') config[k] = String(v).trim(); }
      const field_map = {};
      for (const [k] of FIELD_PATHS) if ((x[`fm_${k}`] || '').trim()) field_map[k] = x[`fm_${k}`].trim();
      const body = { name: x.name.trim(), kind: x.kind, is_enabled: x.is_enabled, base_url: (x.base_url || '').trim(), auth_type: custom(x.kind) ? x.auth_type : 'none', auth_param_name: x.auth_param_name || '',
        request_params: linesToObj(x.request_params), field_map: custom(x.kind) ? field_map : {}, config: custom(x.kind) ? config : (provider?.config || {}), input_currency: x.input_currency || '', market: x.market || 'none',
        refresh_interval_minutes: x.refresh_interval_minutes || 30, min_interval_seconds: x.min_interval_seconds ?? '1', retry_count: x.retry_count ?? 2, retry_delay_seconds: x.retry_delay_seconds ?? '2',
        timeout_seconds: x.timeout_seconds ?? '8', auto_approve: !!x.auto_approve, clear_api_key: !!x.clear_api_key };
      if (x.api_key && x.api_key.trim()) body.api_key = x.api_key.trim();
      if (provider) await api.put(`/api/market-data/providers/${provider.id}`, body); else await api.post('/api/market-data/providers', body);
      m.close(); toast('منبع ذخیره شد.', 'success'); onDone();
    },
  });
  if (provider) f.refs.kind.disabled = true;
  const d = document.getElementById('kind-desc');
  if (d) clear(d).append(notice(first.description, 'info'));
  return f;
}

function openTestDialog(p, kind, done) {
  const ext = h('input', { type: 'text', dir: 'ltr', class: 'ltr-input', placeholder: kind.id_label || 'شناسه', 'aria-label': 'شناسه برای تست' });
  const field = (kind.price_fields || []).length ? h('select', { 'aria-label': 'نوع قیمت' }, [['', 'آخرین معامله'], ['close', 'قیمت پایانی'], ['nav', 'NAV']].map(([v, l]) => h('option', { value: v }, l))) : null;
  const out = h('div');
  const run = async (btn) => {
    btn.disabled = true; clear(out).append(h('div', { class: 'loading' }, h('div', { class: 'spinner' })));
    try {
      const r = await api.post(`/api/market-data/providers/${p.id}/test`, { external_id: ext.value.trim(), price_field: field?.value || '' }, { silent: true });
      clear(out);
      if (r.ok) {
        out.append(notice(`اتصال موفق: ${r.health?.message || ''}${r.health?.latency_ms != null ? ` (${num(r.health.latency_ms)} میلی‌ثانیه)` : ''}`, 'ok'));
        if (r.quote) out.append(h('div', { class: 'card' }, h('div', { class: 'kv' },
          h('div', null, h('span', null, 'قیمت خام'), h('b', null, `${units(r.quote.price)} ${r.quote.unit}`)),
          h('div', null, h('span', null, 'پس از تبدیل واحد'), h('b', null, r.quote.converted_price ? `${units(r.quote.converted_price)} ${p.input_currency || r.quote.unit}` : '—')),
          h('div', null, h('span', null, 'زمان قیمت در منبع'), h('b', null, r.quote.source_time ? fmtDateTime(r.quote.source_time) : 'اعلام نشده')),
          h('div', null, h('span', null, 'نوع قیمت'), h('b', null, { last: 'آخرین معامله', close: 'پایانی', nav: 'NAV' }[r.quote.kind] || r.quote.kind)))),
          r.quote.note ? notice(r.quote.note, 'warn') : null, h('div', { class: 'json-box' }, JSON.stringify(r.quote.extra || {}, null, 1)));
        else out.append(h('p', { class: 'muted' }, 'برای دیدن نمونهٔ قیمت، یک شناسه وارد و دوباره تست کنید.'));
      } else out.append(notice(`${r.error?.message || 'خطا'} [${r.error?.code || ''}]`, 'bad'));
      done();
    } catch (e) { clear(out).append(notice(e.message, 'bad')); }
    btn.disabled = false;
  };
  const go = h('button', { class: 'btn primary', type: 'button', onclick: (e) => run(e.currentTarget) }, icon('play', 15), 'اجرای تست');
  const search = kind.supports_search ? h('button', { class: 'btn', type: 'button', onclick: () => openSymbolSearch({ provider: p, kind, onPick: (s) => { ext.value = s.external_id; } }) }, icon('search', 15), 'جستجوی نماد') : null;
  modal({ title: `تست اتصال «${p.name}»`, body: [h('p', { class: 'muted' }, 'ابتدا سلامت سرویس بررسی می‌شود؛ با وارد کردن شناسه، قیمت نمونه هم خوانده می‌شود. نتیجه در لاگ ذخیره می‌شود (کلید API هرگز نمایش داده نمی‌شود).'),
    h('div', { class: 'inline-form' }, h('label', { style: { flex: 1, minWidth: '160px' } }, h('span', { class: 'lbl' }, kind.id_label || 'شناسه'), ext), field ? h('label', null, h('span', { class: 'lbl' }, 'نوع قیمت'), field) : null, search, go), out] });
}

function logLines(logs) {
  if (!logs.length) return h('p', { class: 'muted' }, 'هنوز لاگی ثبت نشده است.');
  return h('div', null, logs.map((l) => h('div', { class: `log-line ${l.ok ? '' : 'bad'}` },
    h('div', null, badge(l.ok ? (l.status === 'duplicate' ? 'تکراری' : 'موفق') : 'خطا', l.ok ? 'ok' : 'bad'), ' ', h('b', null, l.provider || '—'), l.asset ? ` — ${l.asset}` : '', l.price != null ? ` — ${units(l.price)}` : '', l.latency_ms != null ? ` — ${num(l.latency_ms)}ms` : ''),
    h('div', null, l.message), h('div', { class: 't' }, fmtDateTime(l.ts)))));
}

async function openLogs(p) {
  const body = h('div');
  let only = false;
  const draw = async () => {
    clear(body).append(h('div', { class: 'loading' }, h('div', { class: 'spinner' })));
    const logs = await api.get(`/api/market-data/providers/${p.id}/logs`, { only_errors: only ? 'true' : '', limit: 60 });
    clear(body).append(h('label', { class: 'check', style: { marginBottom: '10px' } }, h('input', { type: 'checkbox', checked: only, onchange: (e) => { only = e.target.checked; draw(); } }), h('span', null, 'فقط خطاها')), logLines(logs));
  };
  modal({ title: `لاگ دریافت «${p.name}»`, wide: true, body });
  await draw();
}

async function deleteProvider(p, done) {
  if (!p.source_count && !p.price_count) {
    if (await confirmDialog({ title: 'حذف منبع', message: `«${p.name}» به هیچ دارایی‌ای وصل نیست و حذف می‌شود.`, danger: true, confirmLabel: 'حذف' })) { await api.del(`/api/market-data/providers/${p.id}`); toast('منبع حذف شد.', 'success'); done(); }
    return;
  }
  const m = modal({ title: `حذف «${p.name}»`, body: [h('p', null, 'این منبع داده‌های وابسته دارد:'), depList({ sources: p.source_count, prices: p.price_count }),
    h('p', { class: 'muted' }, 'پیشنهاد می‌شود بایگانی کنید. حذف دائمی، اتصال‌ها و لاگ‌ها را پاک می‌کند و قیمت‌های ثبت‌شده را (بدون حذف) بدون منبع نگه می‌دارد؛ تراکنش‌ها و بهای خرید تغییر نمی‌کنند.')],
  footer: [h('button', { class: 'btn ghost', onclick: () => m.close() }, 'انصراف'),
    h('button', { class: 'btn', onclick: async () => { m.close(); await api.post(`/api/market-data/providers/${p.id}/archive`); toast('منبع بایگانی شد.', 'success'); done(); } }, icon('archive', 15), 'بایگانی'),
    h('button', { class: 'btn danger', onclick: () => { m.close(); purgeFlow({ base: `/api/market-data/providers/${p.id}`, name: p.name, onDone: done }); } }, 'حذف دائمی…')] });
}

export async function render(root) {
  const [providers, kindsArr, sch, logs] = await Promise.all([api.get('/api/market-data/providers'), api.get('/api/market-data/kinds'), api.get('/api/market-data/scheduler'), api.get('/api/market-data/logs', { limit: 15 })]);
  const kinds = Object.fromEntries(kindsArr.map((k) => [k.kind, k]));
  const done = () => reloadAll();
  root.append(pageHead('منابع قیمت', 'اتصال به TSETMC، بیت‌پین، StreamData، Servix و هر API دلخواه؛ قیمت دستی همیشه به‌عنوان آخرین گزینه در دسترس است.',
    h('button', { class: 'btn primary', onclick: () => openProviderForm({ kinds: kindsArr, onDone: done }) }, icon('plus'), 'منبع جدید'),
    h('button', { class: 'btn', onclick: async (e) => { e.currentTarget.disabled = true; const r = await api.post('/api/market-data/refresh'); const okN = r.results.filter((x) => x.ok).length; toast(r.results.length ? `${num(okN)} از ${num(r.results.length)} دارایی به‌روز شد.` : 'دارایی‌ای با منبع قیمت تعریف نشده است.', r.results.some((x) => !x.ok) ? 'warn' : 'success'); reload(); } }, icon('refresh'), 'دریافت همهٔ قیمت‌ها')));
  root.append(notice('نشانی‌های پیش‌فرض TSETMC و بیت‌پین از کلاینت‌های متن‌باز و مستندات عمومی گرفته شده‌اند و باید با «تست اتصال» روی شبکهٔ شما راستی‌آزمایی شوند. StreamData و Servix آدرس پیش‌فرض ندارند: آدرس و کلید را از سرویس‌دهنده بگیرید.', 'info'));

  // ---- زمان‌بند
  const en = h('input', { type: 'checkbox', checked: sch.enabled, id: 'sch-en' });
  const iv = h('input', { type: 'text', inputmode: 'numeric', dir: 'ltr', class: 'ltr-input', value: sch.default_interval_minutes, style: { maxWidth: '110px' }, 'aria-label': 'بازهٔ پیش‌فرض (دقیقه)' });
  const mh = h('input', { type: 'checkbox', checked: sch.market_hours_only, id: 'sch-mh' });
  const lr = sch.last_result;
  root.append(h('div', { class: 'card', style: { marginBottom: '14px' } }, h('h3', { style: { marginBottom: '10px' } }, 'زمان‌بند دریافت خودکار قیمت'),
    !sch.env_enabled ? notice('زمان‌بند در این اجرا با SCHEDULER_ENABLED=false خاموش است؛ فقط دریافت دستی کار می‌کند.', 'warn') : null,
    h('div', { class: 'inline-form' },
      h('label', { class: 'check' }, en, h('span', null, 'دریافت خودکار فعال باشد')),
      h('label', null, h('span', { class: 'lbl' }, 'بازهٔ پیش‌فرض (دقیقه)'), iv),
      h('label', { class: 'check' }, mh, h('span', null, 'فقط در ساعات باز بودن بازار (برای منابع دارای تقویم)')),
      h('button', { class: 'btn primary', onclick: async () => { await api.put('/api/market-data/scheduler', { scheduler_enabled: en.checked, scheduler_default_interval_minutes: Number(iv.value.replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))) || 30, scheduler_market_hours_only: mh.checked }); toast('تنظیمات زمان‌بند ذخیره شد.', 'success'); reload(); } }, 'ذخیره'),
      h('button', { class: 'btn', onclick: async () => { const r = await api.post('/api/market-data/scheduler/run'); toast(r.skipped ? `اجرا نشد: ${r.skipped === 'disabled' ? 'زمان‌بند غیرفعال است' : r.skipped}` : `${num(r.due)} دارایی سررسید بود: ${num(r.ok)} موفق، ${num(r.failed)} ناموفق، ${num(r.skipped_market_closed)} در ساعت تعطیل بازار`, r.failed ? 'warn' : 'success', 8000); reload(); } }, icon('play', 15), 'اجرای یک دور')),
    h('div', { class: 'meta muted', style: { marginTop: '10px', fontSize: '12.5px' } },
      h('span', null, sch.running ? 'حلقهٔ زمان‌بند در حال اجراست' : 'حلقهٔ زمان‌بند اجرا نمی‌شود'), h('span', null, `آخرین اجرا: ${sch.last_run_at ? fmtDateTime(sch.last_run_at) : '—'}`),
      lr ? h('span', null, `نتیجه: ${num(lr.ok)} موفق / ${num(lr.failed)} ناموفق / ${num(lr.due)} سررسید`) : null, sch.last_error ? h('span', { class: 'neg' }, `خطا: ${sch.last_error}`) : null)));

  // ---- منابع
  const active = providers.filter((p) => !p.is_archived), archived = providers.filter((p) => p.is_archived);
  const card = (p) => {
    const kind = kinds[p.kind] || {};
    const [stText, stKind] = PROVIDER_STATUS[p.status] || ['—', ''];
    const key = p.has_api_key ? 'کلید API ذخیره شده (نمایش داده نمی‌شود)' : (p.api_key_from_env ? 'کلید از متغیر محیطی' : null);
    return h('div', { class: `card mcard ${p.is_archived ? 'archived' : ''}` },
      h('h3', null, h('span', { class: `status-dot ${stKind}` }), p.name, badge(kind.label || p.kind_label, 'blue'), badge(stText, stKind)),
      h('div', { class: 'muted', style: { fontSize: '12.5px' } }, kind.description),
      h('div', { class: 'meta' },
        p.base_url ? h('span', { class: 'kbd', title: p.base_url }, p.base_url.length > 42 ? `${p.base_url.slice(0, 42)}…` : p.base_url) : (p.base_url_from_env ? h('span', null, 'آدرس از متغیر محیطی') : null),
        key ? h('span', null, key) : null, p.kind !== 'manual' ? h('span', null, `بازه ${num(p.refresh_interval_minutes)} دقیقه`) : null,
        p.kind !== 'manual' ? h('span', null, p.auto_approve ? 'تأیید خودکار' : 'نیازمند تأیید دستی') : null),
      h('div', { class: 'kv' },
        h('div', null, h('span', null, 'آخرین دریافت موفق'), h('b', null, p.last_success_at ? fmtDateTime(p.last_success_at) : '—')),
        h('div', null, h('span', null, 'آخرین تلاش'), h('b', null, p.last_attempt_at ? fmtDateTime(p.last_attempt_at) : '—')),
        h('div', null, h('span', null, 'تأخیر'), h('b', null, p.last_latency_ms != null ? `${num(p.last_latency_ms)} ms` : '—')),
        h('div', null, h('span', null, 'دارایی‌های متصل / قیمت‌ها'), h('b', null, `${num(p.source_count)} / ${num(p.price_count)}`))),
      p.last_error ? notice(`آخرین خطا: ${p.last_error}`, 'bad') : null,
      p.consecutive_failures >= 3 ? notice(`${num(p.consecutive_failures)} خطای پیاپی؛ قیمت‌های وابسته ممکن است کهنه شوند.`, 'warn') : null,
      h('div', { class: 'actions' },
        p.kind !== 'manual' && !p.is_archived ? h('button', { class: 'btn tiny primary', onclick: () => openTestDialog(p, kind, done) }, icon('play', 14), 'تست اتصال') : null,
        p.is_archived ? h('button', { class: 'btn tiny', onclick: async () => { await api.post(`/api/market-data/providers/${p.id}/restore`); toast('بازیابی شد.', 'success'); done(); } }, icon('restore', 14), 'بازیابی') : [
          h('button', { class: 'btn tiny', onclick: () => openProviderForm({ provider: p, kinds: kindsArr, onDone: done }) }, icon('edit', 14), 'ویرایش'),
          h('button', { class: 'btn tiny', onclick: async () => { await api.post(`/api/market-data/providers/${p.id}/enable?enabled=${!p.is_enabled}`); toast(p.is_enabled ? 'منبع غیرفعال شد.' : 'منبع فعال شد.', 'success'); done(); } }, p.is_enabled ? 'غیرفعال‌سازی' : 'فعال‌سازی'),
          p.kind !== 'manual' ? h('button', { class: 'btn tiny', onclick: () => openLogs(p) }, 'لاگ‌ها') : null,
          h('button', { class: 'btn tiny', onclick: async () => { if (await confirmDialog({ message: `«${p.name}» بایگانی شود؟ اتصال به دارایی‌ها متوقف می‌شود ولی قیمت‌های ثبت‌شده می‌ماند.`, confirmLabel: 'بایگانی' })) { await api.post(`/api/market-data/providers/${p.id}/archive`); toast('بایگانی شد.', 'success'); done(); } } }, icon('archive', 14), 'بایگانی')],
        p.kind === 'manual' ? null : h('button', { class: 'btn tiny danger', onclick: () => deleteProvider(p, done) }, icon('trash', 14), 'حذف')));
  };
  root.append(h('h2', { class: 'section-title' }, 'منابع تعریف‌شده'), h('div', { class: 'stack-cards two' }, active.map(card)));
  if (archived.length) root.append(h('h2', { class: 'section-title' }, 'بایگانی‌شده'), h('div', { class: 'stack-cards two' }, archived.map(card)));
  root.append(h('h2', { class: 'section-title' }, 'آخرین نتیجهٔ درخواست‌ها', h('small', null, 'موفق و ناموفق')), h('div', { class: 'card' }, logLines(logs)));
}
