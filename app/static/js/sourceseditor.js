// ویرایشگر اولویت منابع قیمت یک دارایی: اصلی ← جایگزین ← دستی + جستجوی نماد (TSETMC/بیت‌پین)
import { api } from './api.js';
import { clear, h, icon, modal, toast, notice } from './ui.js';
import { num } from './format.js';

export async function loadProviders() {
  const [providers, kinds] = await Promise.all([api.get('/api/market-data/providers'), api.get('/api/market-data/kinds')]);
  return { providers: providers.filter((p) => !p.is_archived), kinds: Object.fromEntries(kinds.map((k) => [k.kind, k])) };
}

export function openSymbolSearch({ provider, kind, onPick }) {
  const input = h('input', { type: 'search', placeholder: kind.supports_search ? 'نام یا نماد (حداقل ۲ نویسه)…' : 'جستجو پشتیبانی نمی‌شود', autocomplete: 'off' });
  const results = h('div', null, h('p', { class: 'muted' }, 'عبارت را وارد و «جستجو» را بزنید.'));
  const run = async () => {
    const q = input.value.trim();
    clear(results).append(h('div', { class: 'loading' }, h('div', { class: 'spinner' })));
    try {
      const r = await api.get(`/api/market-data/providers/${provider.id}/search`, { q }, { silent: true });
      clear(results);
      if (!r.items.length) { results.append(h('p', { class: 'muted' }, 'نتیجه‌ای پیدا نشد.')); return; }
      r.items.forEach((s) => results.append(h('div', { class: 'member-row', style: { gridTemplateColumns: 'minmax(0,1fr) auto' } },
        h('div', null, h('b', null, s.symbol || s.external_id), ' ', h('span', { class: 'muted' }, s.name), h('div', { class: 'meta muted', style: { fontSize: '12px' } }, h('span', { class: 'kbd' }, s.external_id), s.active === false ? ' • غیرفعال' : '')),
        h('button', { class: 'btn tiny primary', type: 'button', onclick: () => { onPick(s); m.close(); } }, 'انتخاب'))));
    } catch (e) { clear(results).append(notice(e.message, 'bad')); }
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); run(); } });
  const m = modal({ title: `جستجوی نماد در ${provider.name}`, body: [h('div', { class: 'inline-form', style: { marginBottom: '10px' } }, input, h('button', { class: 'btn primary', type: 'button', onclick: run }, icon('search', 16), 'جستجو')),
    kind.supports_search ? null : notice('این منبع جستجوی نماد ندارد؛ شناسه را دستی وارد کنید.', 'info'), results] });
  setTimeout(() => input.focus(), 250);
}

/** ویرایشگر: initial = sources دارایی (با provider_id, external_id, price_field, interval_minutes, is_enabled) */
export function sourcesEditor({ providers, kinds, initial = [], currency }) {
  const rows = [];
  const box = h('div');
  const list = h('div');
  const mk = (src = {}) => {
    const sel = h('select', { 'aria-label': 'منبع' }, providers.map((p) => h('option', { value: p.id }, `${p.name}${p.is_enabled ? '' : ' (غیرفعال)'}`)));
    if (src.provider_id) sel.value = String(src.provider_id);
    const ext = h('input', { type: 'text', dir: 'ltr', class: 'ltr-input', placeholder: 'شناسه نزد منبع', value: src.external_id || '', 'aria-label': 'شناسه در منبع' });
    const field = h('select', { 'aria-label': 'نوع قیمت' }, [['', 'پیش‌فرض'], ['last', 'آخرین معامله'], ['close', 'قیمت پایانی'], ['nav', 'NAV صندوق']].map(([v, l]) => h('option', { value: v }, l)));
    field.value = src.price_field || '';
    const interval = h('input', { type: 'text', inputmode: 'numeric', dir: 'ltr', class: 'ltr-input', placeholder: 'دقیقه', value: src.interval_minutes || '', style: { maxWidth: '84px' }, 'aria-label': 'بازه به‌روزرسانی (دقیقه)', title: 'بازهٔ به‌روزرسانی این منبع (دقیقه)؛ خالی = پیش‌فرض منبع' });
    const en = h('input', { type: 'checkbox', checked: src.is_enabled !== false, 'aria-label': 'فعال' });
    const kind = () => kinds[providers.find((p) => String(p.id) === sel.value)?.kind] || {};
    const label = h('small', { class: 'hint' });
    const searchBtn = h('button', { class: 'btn tiny', type: 'button', onclick: () => {
      const prov = providers.find((p) => String(p.id) === sel.value);
      openSymbolSearch({ provider: prov, kind: kind(), onPick: (s) => { ext.value = s.external_id; } });
    } }, icon('search', 14), 'جستجو');
    const sync = () => {
      const k = kind();
      const manual = k.default_unit !== undefined && providers.find((p) => String(p.id) === sel.value)?.kind === 'manual';
      ext.hidden = manual; searchBtn.hidden = manual || !k.supports_search; field.hidden = !(k.price_fields || []).length; interval.hidden = manual;
      label.textContent = manual ? 'آخرین قیمت دستی تأییدشده استفاده می‌شود.' : (k.id_label || '');
    };
    sel.addEventListener('change', sync);
    const row = { el: null, get: () => ({ provider_id: Number(sel.value), external_id: ext.value.trim(), price_field: field.hidden ? '' : field.value, is_enabled: en.checked, interval_minutes: interval.hidden || !interval.value.trim() ? null : Number(interval.value.replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))) }) };
    const up = h('button', { class: 'icon-btn', type: 'button', title: 'اولویت بالاتر', 'aria-label': 'اولویت بالاتر', onclick: () => { const i = rows.indexOf(row); if (i > 0) { rows.splice(i, 1); rows.splice(i - 1, 0, row); draw(); } } }, h('span', { style: { transform: 'rotate(-90deg)', display: 'inline-flex' } }, icon('chevron', 16)));
    const del = h('button', { class: 'icon-btn', type: 'button', title: 'حذف منبع', 'aria-label': 'حذف منبع', onclick: () => { rows.splice(rows.indexOf(row), 1); draw(); } }, icon('trash', 16));
    row.badge = h('span', { class: 'badge info' });
    row.el = h('div', { class: 'src-row' },
      h('label', null, h('span', { class: 'lbl' }, row.badge), sel),
      h('label', null, h('span', { class: 'lbl' }, 'شناسه در منبع'), h('div', { class: 'inline-form', style: { flexWrap: 'nowrap' } }, ext, searchBtn), label, field),
      h('label', null, h('span', { class: 'lbl' }, 'بازه (دقیقه)'), interval),
      h('label', { class: 'check' }, en, h('span', null, 'فعال')),
      h('div', { class: 'row-actions' }, up, del));
    sync();
    return row;
  };
  const draw = () => {
    clear(list);
    rows.forEach((r, i) => { r.badge.textContent = i === 0 ? 'منبع اصلی' : (i === 1 ? 'جایگزین' : `جایگزین ${num(i)}`); list.append(r.el); });
    if (!rows.length) list.append(h('p', { class: 'muted', style: { margin: 0 } }, 'منبعی تعریف نشده؛ قیمت فقط دستی ثبت می‌شود.'));
  };
  initial.forEach((s) => rows.push(mk(s)));
  const add = h('button', { class: 'btn tiny', type: 'button', onclick: () => { rows.push(mk({})); draw(); } }, icon('plus', 14), 'افزودن منبع');
  box.append(h('div', { class: 'form-section' }, 'منابع قیمت (به ترتیب اولویت)'), list, add,
    h('small', { class: 'hint', style: { display: 'block', marginTop: '6px' } }, `اگر منبع اصلی خطا بدهد، به‌ترتیب منبع بعدی امتحان می‌شود. قیمت قدیمی هرگز به‌عنوان قیمت روز استفاده نمی‌شود.${currency ? ` واحد قیمت دارایی: ${currency}.` : ''}`));
  draw();
  return { node: box, providers, get: () => rows.map((r, i) => ({ ...r.get(), priority: i + 1 })), validate: () => {
    for (const r of rows) { const g = r.get(); const p = providers.find((x) => x.id === g.provider_id); if (p && p.kind !== 'manual' && !g.external_id) return `برای منبع «${p.name}» شناسهٔ دارایی نزد منبع را وارد کنید.`; }
    return null;
  } };
}
