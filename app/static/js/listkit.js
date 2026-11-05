// اجزای مشترک صفحه‌های مدیریت: نوار جستجو/فیلتر، صفحه‌بندی، حذف دائمی چندمرحله‌ای، نمایش وابستگی‌ها
import { api } from './api.js';
import { enDigits, num } from './format.js';
import { clear, h, icon, modal, notice, toast } from './ui.js';

export function debounce(fn, ms = 280) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** نوار ابزار: جستجو + فیلترهای select. onChange با مقدار فعلی همهٔ فیلترها صدا زده می‌شود. */
export function toolbar({ placeholder = 'جستجو…', q = '', filters = [], onChange }) {
  const values = { q };
  filters.forEach((f) => { values[f.name] = f.value ?? ''; });
  const input = h('input', { type: 'search', placeholder, value: q, 'aria-label': placeholder, autocomplete: 'off' });
  const fire = () => onChange({ ...values });
  input.addEventListener('input', debounce(() => { values.q = input.value.trim(); fire(); }));
  const selects = filters.map((f) => {
    const sel = h('select', { 'aria-label': f.label, title: f.label }, f.options.map((o) => h('option', { value: o.value }, o.label)));
    sel.value = String(values[f.name]);
    sel.addEventListener('change', () => { values[f.name] = sel.value; fire(); });
    return sel;
  });
  return h('div', { class: 'toolbar card' },
    h('div', { class: 'search' }, icon('search', 17), input),
    h('div', { class: 'tb-filters' }, selects));
}

export function pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? (page - 1) * pageSize + 1 : 0;
  const to = Math.min(total, page * pageSize);
  return h('div', { class: 'pager' },
    h('span', null, total ? `نمایش ${num(from)} تا ${num(to)} از ${num(total)} مورد` : 'موردی یافت نشد'),
    h('div', { class: 'btns' },
      h('button', { class: 'btn tiny', disabled: page <= 1, onclick: () => onPage(page - 1) }, 'قبلی'),
      h('span', null, `صفحه ${num(page)} از ${num(pages)}`),
      h('button', { class: 'btn tiny', disabled: page >= pages, onclick: () => onPage(page + 1) }, 'بعدی')));
}

const DEP_LABEL = { transactions: 'تراکنش', prices: 'قیمت ثبت‌شده', price_sources: 'منبع قیمت متصل', portfolios: 'عضویت در سبد', fetch_logs: 'لاگ دریافت',
  assets: 'دارایی', sources: 'اتصال به دارایی', plan_periods: 'دورهٔ برنامه' };

export function depList(deps) {
  const items = Object.entries(deps || {}).filter(([, n]) => Number(n) > 0);
  if (!items.length) return h('p', { class: 'muted' }, 'هیچ وابستگی‌ای ثبت نشده است.');
  return h('ul', { class: 'steps' }, items.map(([k, n]) => h('li', null, `${num(n)} ${DEP_LABEL[k] || k}`)));
}

/**
 * حذف دائمی دو مرحله‌ای: ۱) نمایش وابستگی‌ها و دریافت توکن ۲) تایپ عبارت تأیید.
 * base مثل /api/assets/12 (باید purge/request و purge/confirm داشته باشد).
 */
export async function purgeFlow({ base, name, onDone }) {
  let req;
  try { req = await api.post(`${base}/purge/request`); } catch { return; }
  const phrase = h('input', { type: 'text', placeholder: req.phrase, autocomplete: 'off', 'aria-label': 'عبارت تأیید' });
  const err = h('div', { class: 'form-error', hidden: true });
  const go = h('button', { class: 'btn danger', type: 'button', disabled: true }, 'حذف دائمی');
  phrase.addEventListener('input', () => { go.disabled = phrase.value.trim() !== req.phrase; });
  const m = modal({
    title: `حذف دائمی «${name}»`,
    body: [
      notice(req.warning || 'حذف دائمی قابل بازگشت نیست.', 'bad'),
      h('p', null, 'موارد زیر همراه با این مورد حذف می‌شوند:'), depList(req.dependencies),
      h('label', null, h('span', { class: 'lbl' }, `برای تأیید عبارت «${req.phrase}» را تایپ کنید`), phrase), err],
    footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), go],
  });
  go.addEventListener('click', async () => {
    go.disabled = true;
    try {
      await api.post(`${base}/purge/confirm`, { token: req.token, phrase: phrase.value.trim() }, { silent: true });
      m.close(); toast('حذف دائمی انجام شد (پشتیبان قبلی گرفته شد).', 'success'); onDone && onDone();
    } catch (e) { err.textContent = e.message; err.hidden = false; go.disabled = false; }
  });
}

export const optionsFrom = (list, value = (x) => x.id, label = (x) => x.name, first) => [...(first ? [first] : []), ...list.map((x) => ({ value: value(x), label: label(x) }))];
export const toInt = (v) => Number(enDigits(String(v)));
