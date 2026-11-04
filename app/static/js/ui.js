// کتابخانه کوچک رابط کاربری: ساخت عناصر، مودال، فرم، جدول، اعلان
import { calendar, state } from './state.js';
import { dateInputToISO, isoToDateInput, parseDecimal, todayISO, enDigits, fmtDate, faDigits } from './format.js';

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs && typeof attrs === 'object' && !(attrs instanceof Node) && !Array.isArray(attrs)) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  } else if (attrs !== undefined && attrs !== null) children.unshift(attrs);
  append(el, children);
  return el;
}
export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

// ---------------- آیکن‌ها ----------------
const ICONS = {
  dashboard: 'M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 9h8V3h-8z',
  portfolio: 'M3 7h18v13H3zM8 7V4h8v3M3 13h18',
  assets: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5',
  tx: 'M7 4v14M7 18l-3-3M7 18l3-3M17 20V6M17 6l-3 3M17 6l3 3',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
  target: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 16a4 4 0 100-8 4 4 0 000 8zM12 12h.01',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  report: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7',
  settings: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 00-2-1.2L14 3h-4l-.6 2.7a7 7 0 00-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 002 1.2L10 21h4l.6-2.7a7 7 0 002-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z',
  price: 'M4 18l5-6 4 3 7-9M4 21h16',
  plus: 'M12 5v14M5 12h14',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6',
  download: 'M12 4v11M7 11l5 5 5-5M5 20h14',
  upload: 'M12 16V5M7 9l5-5 5 5M5 20h14',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'M6 6l12 12M18 6L6 18',
  check: 'M5 13l4 4L19 7',
  alert: 'M12 4l9 16H3zM12 10v4M12 17h.01',
  info: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v5M12 8h.01',
  refresh: 'M20 11a8 8 0 10-2.3 5.7M20 5v6h-6',
  back: 'M9 6l6 6-6 6',
  platform: 'M3 20h18M5 20V9l7-5 7 5v11M9 20v-6h6v6',
  folder: 'M3 6h6l2 2h10v11H3zM3 11h18',
  sources: 'M5 12a7 7 0 0114 0M8.5 12a3.5 3.5 0 017 0M12 12h.01M12 15v5M9 20h6',
  search: 'M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4',
  archive: 'M3 5h18v4H3zM5 9v10h14V9M10 13h4',
  restore: 'M4 12a8 8 0 112.3 5.7M4 18v-6h6',
  play: 'M7 5l12 7-12 7z',
  chevron: 'M9 6l6 6-6 6',
  pulse: 'M3 12h4l3-8 4 16 3-8h4',
  link: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
  globe: 'M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
};
export function icon(name, size = 18) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('width', size); s.setAttribute('height', size);
  s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.7');
  s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round'); s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', ICONS[name] || ICONS.info); s.append(p);
  return s;
}

// ---------------- اعلان ----------------
export function toast(message, kind = 'info', ms = 4500) {
  let box = document.getElementById('toasts');
  if (!box) { box = h('div', { id: 'toasts', 'aria-live': 'polite' }); document.body.append(box); }
  const t = h('div', { class: `toast ${kind}`, role: 'status' }, icon(kind === 'error' ? 'alert' : kind === 'success' ? 'check' : 'info', 18), h('span', null, message));
  box.append(t);
  requestAnimationFrame(() => t.classList.add('show'));
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, ms);
}
export function toastWarnings(list) { (list || []).forEach((w) => toast(w, 'warn', 8000)); }

// ---------------- مودال ----------------
let modalStack = [];
export function modal({ title, body, footer, wide = false, onClose }) {
  const overlay = h('div', { class: 'overlay' });
  const dlg = h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
  const close = () => {
    overlay.classList.remove('show');
    setTimeout(() => overlay.remove(), 200);
    modalStack = modalStack.filter((m) => m !== api);
    document.removeEventListener('keydown', onKey);
    onClose && onClose();
  };
  const onKey = (e) => { if (e.key === 'Escape' && modalStack[modalStack.length - 1] === api) close(); };
  dlg.append(
    h('div', { class: 'modal-head' }, h('h3', null, title), h('button', { class: 'icon-btn', 'aria-label': 'بستن', onclick: close }, icon('close'))),
    h('div', { class: 'modal-body' }, body),
    ...(footer ? [h('div', { class: 'modal-foot' }, footer)] : []),
  );
  overlay.append(dlg);
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });
  document.body.append(overlay);
  requestAnimationFrame(() => overlay.classList.add('show'));
  document.addEventListener('keydown', onKey);
  const api = { close, el: dlg };
  modalStack.push(api);
  const first = dlg.querySelector('input,select,textarea,button.primary');
  first && setTimeout(() => first.focus(), 60);
  return api;
}

export function closeAllModals() { [...modalStack].forEach((m) => m.close()); }

export function confirmDialog({ title = 'تأیید', message, confirmLabel = 'تأیید', danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const m = modal({
      title, body: h('p', { class: 'confirm-text' }, message), onClose: () => finish(false),
      footer: [
        h('button', { class: 'btn ghost', onclick: () => { finish(false); m.close(); } }, 'انصراف'),
        h('button', { class: `btn ${danger ? 'danger' : 'primary'}`, onclick: () => { finish(true); m.close(); } }, confirmLabel),
      ],
    });
  });
}

// ---------------- فیلد تاریخ ----------------
export function dateField(name, isoValue, { required = true } = {}) {
  const cal = calendar();
  const wrap = h('div', { class: 'date-field' });
  let input;
  if (cal === 'jalali') {
    input = h('input', { type: 'text', name, inputmode: 'numeric', autocomplete: 'off', placeholder: faDigits('1405/01/01'), dir: 'ltr', class: 'ltr-input' });
    input.value = faDigits(isoToDateInput(isoValue || (required ? todayISO() : '')));
  } else {
    input = h('input', { type: 'date', name });
    input.value = isoValue || (required ? todayISO() : '');
  }
  const hint = h('small', { class: 'date-hint' });
  const update = () => {
    const iso = getISO();
    hint.textContent = '';
    if (cal === 'jalali' && input.value.trim()) {
      hint.textContent = iso ? `میلادی: ${iso}` : 'تاریخ نامعتبر (قالب: سال/ماه/روز)';
      hint.classList.toggle('bad', !iso);
    }
  };
  const getISO = () => {
    const v = input.value.trim();
    if (!v) return null;
    return cal === 'jalali' ? dateInputToISO(v, 'jalali') : v;
  };
  input.addEventListener('input', update);
  const todayBtn = h('button', { type: 'button', class: 'btn tiny ghost', onclick: () => { input.value = cal === 'jalali' ? faDigits(isoToDateInput(todayISO())) : todayISO(); update(); input.dispatchEvent(new Event('change', { bubbles: true })); } }, 'امروز');
  wrap.append(h('div', { class: 'date-row' }, input, todayBtn), hint);
  wrap.getValue = getISO;
  wrap.setValue = (iso) => { input.value = cal === 'jalali' ? faDigits(isoToDateInput(iso)) : iso; update(); };
  update();
  return wrap;
}

// ---------------- فرم ----------------
export function buildForm(fields, values = {}, { onChange } = {}) {
  const form = h('form', { class: 'form-grid', novalidate: true, autocomplete: 'off' });
  const refs = {};
  const rows = {};
  const getValues = () => {
    const out = {};
    for (const f of fields) {
      const r = refs[f.name];
      if (!r) continue;
      if (f.type === 'checkbox') out[f.name] = r.checked;
      else if (f.type === 'date') out[f.name] = r.getValue();
      else if (f.type === 'datetime') { const d = r.date.getValue(); out[f.name] = d ? `${d}T${r.time.value || '00:00'}:00` : null; }
      else if (f.type === 'decimal') out[f.name] = r.value.trim() === '' ? null : parseDecimal(r.value);
      else if (f.type === 'int') out[f.name] = r.value.trim() === '' ? null : Number(enDigits(r.value));
      else if (f.type === 'select') out[f.name] = r.value === '' ? null : (f.numeric ? Number(r.value) : r.value);
      else out[f.name] = r.value;
    }
    return out;
  };
  const refresh = () => {
    const vals = getValues();
    for (const f of fields) {
      if (f.show) rows[f.name].hidden = !f.show(vals);
      if (f.options && typeof f.optionsFn === 'function') { /* dynamic handled by onChange */ }
    }
    onChange && onChange(vals, api);
  };
  for (const f of fields) {
    if (f.type === 'section') { const d = h('div', { class: 'form-section' }, f.label); rows[f.name] = d; form.append(d); continue; }
    let control;
    const v = values[f.name];
    if (f.type === 'select') {
      control = h('select', { name: f.name }, (f.options || []).map((o) => h('option', { value: o.value ?? '' }, o.label)));
      control.value = v === undefined || v === null ? (f.options?.[0]?.value ?? '') : String(v);
    } else if (f.type === 'checkbox') {
      control = h('input', { type: 'checkbox', name: f.name }); control.checked = !!v;
    } else if (f.type === 'textarea') {
      control = h('textarea', { name: f.name, rows: 2, placeholder: f.placeholder || '', dir: f.ltr ? 'ltr' : undefined, class: f.ltr ? 'ltr-input' : '' }); control.value = v || '';
    } else if (f.type === 'date') {
      control = dateField(f.name, v, { required: f.required !== false });
    } else if (f.type === 'datetime') {
      const iso = v || `${todayISO()}T${new Date().toTimeString().slice(0, 5)}`;
      const date = dateField(f.name, iso.slice(0, 10));
      const time = h('input', { type: 'time', name: f.name + '_time', value: iso.slice(11, 16) || '12:00' });
      control = h('div', { class: 'datetime-field' }, date, time); control.date = date; control.time = time;
    } else {
      const isNum = f.type === 'decimal' || f.type === 'int';
      control = h('input', { type: f.inputType || 'text', name: f.name, inputmode: isNum ? 'decimal' : 'text', placeholder: f.placeholder || '', dir: (isNum || f.ltr) ? 'ltr' : undefined, class: (isNum || f.ltr) ? 'ltr-input' : '' });
      control.value = v === undefined || v === null ? '' : (isNum ? faDigits(v) : v);
    }
    refs[f.name] = control;
    const label = h('label', { class: f.type === 'checkbox' ? 'check' : '' }, f.type === 'checkbox' ? [control, h('span', null, f.label)] : [h('span', { class: 'lbl' }, f.label, f.required ? h('b', { class: 'req' }, ' *') : null), control], f.hint ? h('small', { class: 'hint' }, f.hint) : null);
    if (f.wide || f.type === 'textarea') label.classList.add('span2');
    rows[f.name] = label;
    form.append(label);
    const evt = f.type === 'select' || f.type === 'checkbox' ? 'change' : 'input';
    control.addEventListener(evt, refresh);
    control.addEventListener('change', refresh);
    if (f.type === 'decimal') control.addEventListener('blur', () => { if (control.value.trim()) control.value = groupDecimalText(control.value); });
  }
  const api = { form, refs, getValues, refresh, setOptions(name, options, keep = true) {
    const sel = refs[name]; const cur = sel.value;
    clear(sel); options.forEach((o) => sel.append(h('option', { value: o.value ?? '' }, o.label)));
    if (keep && options.some((o) => String(o.value) === cur)) sel.value = cur;
  }, setValue(name, val) { const r = refs[name]; if (r.setValue) r.setValue(val); else if (r.type === 'checkbox') r.checked = val; else r.value = val; refresh(); } };
  refresh();
  return api;
}

export function validateRequired(fields, vals) {
  for (const f of fields) {
    if (f.show && !f.show(vals)) continue;
    const v = vals[f.name];
    if (f.required && (v === null || v === undefined || v === '')) return `«${f.label}» الزامی است.`;
    if ((f.type === 'decimal' || f.type === 'int') && v !== null && Number.isNaN(v)) return `«${f.label}» باید عدد معتبر باشد.`;
    if ((f.type === 'date') && f.required !== false && !v) return `«${f.label}» نامعتبر است.`;
    if (f.type === 'datetime' && !v) return `«${f.label}» نامعتبر است.`;
  }
  return null;
}

export function formModal({ title, fields, values = {}, submitLabel = 'ذخیره', onSubmit, onChange, wide = false, extra }) {
  const f = buildForm(fields, values, { onChange });
  const err = h('div', { class: 'form-error', role: 'alert', hidden: true });
  let busy = false;
  const submit = async () => {
    if (busy) return;
    const vals = f.getValues();
    const msg = validateRequired(fields, vals);
    if (msg) { err.textContent = msg; err.hidden = false; return; }
    err.hidden = true; busy = true; btn.disabled = true;
    try { await onSubmit(vals, m); } catch (e) { err.textContent = e.message || 'خطا'; err.hidden = false; } finally { busy = false; btn.disabled = false; }
  };
  f.form.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  const btn = h('button', { class: 'btn primary', type: 'button', onclick: submit }, submitLabel);
  const m = modal({ title, wide, body: [extra || null, f.form, err], footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), btn] });
  return { ...f, modal: m, close: m.close };
}

// ---------------- اجزای نمایشی ----------------
export function badge(text, kind = 'muted') { return h('span', { class: `badge ${kind}` }, text); }

export function table(columns, rows, { empty = 'داده‌ای برای نمایش وجود ندارد.', rowClass, foot, compact = false } = {}) {
  if (!rows.length) return h('div', { class: 'empty-note' }, empty);
  const thead = h('thead', null, h('tr', null, columns.map((c) => h('th', { class: c.class || '' }, c.label))));
  const tbody = h('tbody', null, rows.map((r, i) => h('tr', { class: rowClass ? rowClass(r) : '' }, columns.map((c) => {
    const v = c.render ? c.render(r, i) : r[c.key];
    return h('td', { class: c.class || '', 'data-label': c.label }, v === null || v === undefined ? '—' : v);
  }))));
  const tfoot = foot ? h('tfoot', null, h('tr', null, foot.map((c) => h('td', { class: c.class || '', colspan: c.colspan }, c.content)))) : null;
  return h('div', { class: 'table-wrap' }, h('table', { class: `data stack${compact ? ' compact' : ''}` }, thead, tbody, tfoot));
}

export function kpi({ label, value, sub, tone = '', progress, hint, valueClass = '' }) {
  return h('div', { class: `card kpi ${tone}` },
    h('div', { class: 'kpi-label' }, label, hint ? h('span', { class: 'tip', title: hint, tabindex: '0' }, icon('info', 14)) : null),
    h('div', { class: `kpi-value ${valueClass}` }, value),
    progress !== undefined && progress !== null ? h('div', { class: 'progress' }, h('span', { style: { width: `${Math.max(0, Math.min(100, progress))}%` } })) : null,
    sub ? h('div', { class: 'kpi-sub' }, sub) : null);
}

export function pageHead(title, subtitle, ...actions) {
  return h('div', { class: 'page-head' }, h('div', null, h('h1', null, title), subtitle ? h('p', { class: 'muted' }, subtitle) : null), h('div', { class: 'page-actions' }, ...actions));
}
export const loadingBox = () => h('div', { class: 'loading' }, h('div', { class: 'spinner' }), h('span', null, 'در حال بارگذاری…'));
export const emptyState = (title, text, action) => h('div', { class: 'card empty-state' }, h('h3', null, title), h('p', { class: 'muted' }, text), action || null);
export const notice = (text, kind = 'warn') => h('div', { class: `notice ${kind}` }, icon(kind === 'info' ? 'info' : 'alert', 18), h('div', null, text));
const TYPE_COLORS = { gold: '#e8b84a', blue: '#4aa3ff', green: '#2fd29a', red: '#ff5d73', slate: '#8fa0c3' };
export function typeColor(t) {
  const info = state.meta?.asset_types?.find((x) => x.key === t);
  const c = info?.color || '';
  return c.startsWith('#') ? c : (TYPE_COLORS[c] || ({ gold: '#e8b84a', digital: '#4aa3ff', index: '#4aa3ff', fund: '#6f86ff' }[t]) || '#62759d');
}
export const typeDot = (t) => h('span', { class: `type-dot t-${t}`, style: { background: typeColor(t) }, 'aria-hidden': 'true' });

export function downloadBlob(blob, filename) {
  const a = h('a', { href: URL.createObjectURL(blob), download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// ---------------- ارقام فارسی ----------------
// هر متن نمایشی با ارقام لاتین (مثلاً پیام‌های سرور) به ارقام فارسی تبدیل می‌شود؛
// فقط محتوای عمداً چپ‌به‌راست (نشانی، کلید، کد) و فیلدهای ورودی دست‌نخورده می‌مانند.
const KEEP = 'script,style,textarea,input,code,pre,.kbd,[dir=ltr],.ltr-text,.ltr-input,[data-keep-digits]';
const LATIN = /[0-9]/;
function fixDigits(node) {
  if (node.nodeType === 3) {
    if (LATIN.test(node.nodeValue) && !(node.parentElement && node.parentElement.closest(KEEP))) node.nodeValue = faDigits(node.nodeValue);
    return;
  }
  if (node.nodeType !== 1 || node.closest(KEEP)) return;
  const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  const list = [];
  for (let t = w.nextNode(); t; t = w.nextNode()) list.push(t);
  list.forEach(fixDigits);
}
export function installDigitFix(root = document.body) {
  fixDigits(root);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === 'characterData') fixDigits(m.target);
      else m.addedNodes.forEach(fixDigits);
    }
  }).observe(root, { childList: true, subtree: true, characterData: true });
}
// قالب‌بندی هزارگان برای فیلدهای مبلغ هنگام ترک فیلد (مقدار با parseDecimal همچنان درست خوانده می‌شود)
export function groupDecimalText(v) {
  const t = enDigits(v);
  if (!/^-?\d+(\.\d+)?$/.test(t)) return v;
  const [i, f] = t.replace('-', '').split('.');
  const g = i.replace(/\B(?=(\d{3})+(?!\d))/g, '٬');
  return faDigits(`${t.startsWith('-') ? '-' : ''}${g}${f ? '٫' + f : ''}`);
}
