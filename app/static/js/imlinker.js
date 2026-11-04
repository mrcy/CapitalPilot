// انتخاب و تأیید نمادِ Iran Market Data برای یک دارایی. هیچ تطبیق خودکاری انجام نمی‌شود:
// کاربر نماد را جستجو/انتخاب می‌کند، قیمت و واحد را می‌بیند و صراحتاً تأیید می‌کند.
import { api } from './api.js';
import { debounce } from './listkit.js';
import { badge, clear, h, icon, modal, notice } from './ui.js';
import { CATEGORY_LABEL, SYMBOL_STATUS, currencyLabel, fmtDateTime, num, unitName, units } from './format.js';

const ltr = (t) => h('span', { dir: 'ltr', class: 'ltr-text' }, t);
export const symStatusBadge = (s) => { const [t, k] = SYMBOL_STATUS[s] || [s, '']; return badge(t, k); };
export const priceWithCur = (p, c) => (p === null || p === undefined ? '—' : `${c === 'IRT' ? num(p, 2) : units(p)} ${currencyLabel(c)}`);
export const symName = (s) => s.name_fa && s.name_fa !== s.symbol ? s.name_fa : (s.name_en && s.name_en !== s.symbol ? s.name_en : s.symbol);

function preview(d, currency) {
  const blockers = [...(d.link_blockers || [])];
  if (currency && d.currency && currency !== d.currency && !(['IRT', 'IRR'].includes(currency) && ['IRT', 'IRR'].includes(d.currency)) && !blockers.some((b) => b.includes('سازگار'))) {
    blockers.push(`واحد نماد (${d.currency}) با واحد قیمت دارایی (${currency}) سازگار نیست.`);
  }
  const kv = (l, v) => h('div', null, h('span', null, l), h('b', null, v ?? '—'));
  const box = h('div', { class: 'card im-preview', 'data-testid': 'im-preview' },
    h('h3', null, symName(d), ' ', ltr(d.symbol), ' ', symStatusBadge(d.status)),
    h('p', { class: 'muted', style: { margin: '2px 0 8px' } }, d.status_reason || 'قیمت معتبر است و در ارزش‌گذاری استفاده می‌شود.'),
    h('div', { class: 'kv kv-3' },
      kv('آخرین قیمت', priceWithCur(d.price, d.currency)), kv('واحد پول', currencyLabel(d.currency)), kv('واحد قیمت', `${unitName(d.unit)}${d.unit_size && Number(d.unit_size) !== 1 ? ` (×${num(d.unit_size)})` : ''}`),
      kv('دسته', CATEGORY_LABEL[d.category]), kv('منبع اصلی', d.source || '—'), kv('زمان قیمت', d.price_time ? fmtDateTime(d.price_time) : '—')));
  blockers.forEach((b) => box.append(notice(b, 'bad')));
  return { box, blockers };
}

export function openSymbolLinker({ asset = null, currency = '', current = '', onConfirm }) {
  const input = h('input', { type: 'search', placeholder: 'نام فارسی/انگلیسی یا نماد…', autocomplete: 'off', 'aria-label': 'جستجوی نماد', 'data-testid': 'im-search' });
  const compat = h('input', { type: 'checkbox', checked: !!currency });
  const results = h('div', { class: 'im-results' });
  const pane = h('div', { class: 'im-pane' });
  const confirmBtn = h('button', { class: 'btn primary', type: 'button', disabled: true, 'data-testid': 'im-confirm' }, icon('link', 15), 'تأیید و اتصال این نماد');
  let seq = 0;
  const row = (s, tag) => h('div', { class: 'member-row im-row', style: { gridTemplateColumns: 'minmax(0,1fr) auto' } },
    h('div', null, h('b', null, symName(s)), ' ', ltr(s.symbol), s.symbol === current ? badge('نمادِ فعلی', 'blue') : null, tag ? badge(tag, 'info') : null,
      h('div', { class: 'meta muted', style: { fontSize: '12px' } }, h('span', null, priceWithCur(s.price, s.currency)), h('span', null, CATEGORY_LABEL[s.category]), symStatusBadge(s.status))),
    h('button', { class: 'btn tiny primary', type: 'button', onclick: () => select(s.symbol) }, 'مشاهده و انتخاب'));
  const search = async () => {
    const my = ++seq; const q = input.value.trim();
    clear(results).append(h('div', { class: 'loading' }, h('div', { class: 'spinner' })));
    try {
      const out = [];
      if (!q && asset?.id) {
        const sg = await api.get('/api/iran-market/suggest', { asset_id: asset.id }, { silent: true });
        if (my !== seq) return;
        sg.items.forEach((s) => out.push(row(s, 'پیشنهاد')));
        if (out.length) out.unshift(h('p', { class: 'muted', style: { margin: '0 0 6px' } }, 'پیشنهادها فقط راهنما هستند؛ اتصال بدون تأیید شما انجام نمی‌شود.'));
      }
      if (q || !out.length) {
        const r = await api.get('/api/iran-market/symbols', { q, currency: compat.checked ? currency : '', page_size: 30, sort: 'name' }, { silent: true });
        if (my !== seq) return;
        if (!r.items.length) out.push(h('p', { class: 'muted' }, q ? 'نمادی پیدا نشد. اگر هنوز داده‌ای دریافت نشده، از صفحهٔ «بازار جامع ایران» دریافت دستی بزنید.' : 'عبارت جست‌وجو را وارد کنید.'));
        r.items.forEach((s) => out.push(row(s)));
        if (r.total > r.items.length) out.push(h('p', { class: 'muted' }, `${num(r.total)} نتیجه؛ برای محدودکردن، عبارت دقیق‌تری بنویسید.`));
      }
      clear(results).append(...out);
    } catch (e) { clear(results).append(notice(e.message, 'bad')); }
  };
  const select = async (sym) => {
    clear(pane).append(h('div', { class: 'loading' }, h('div', { class: 'spinner' })));
    confirmBtn.disabled = true;
    try {
      const d = await api.get(`/api/iran-market/symbols/${encodeURIComponent(sym)}`, undefined, { silent: true });
      const { box, blockers } = preview(d, currency);
      const ack1 = h('input', { type: 'checkbox', 'data-testid': 'im-ack' });
      const needUnit = d.unit && d.unit !== 'unit';
      const ack2 = needUnit ? h('input', { type: 'checkbox', 'data-testid': 'im-ack-unit' }) : null;
      const sync = () => { confirmBtn.disabled = blockers.length > 0 || !ack1.checked || (ack2 && !ack2.checked); };
      ack1.addEventListener('change', sync); ack2?.addEventListener('change', sync);
      confirmBtn.onclick = () => { onConfirm(d); m.close(); };
      clear(pane).append(box, blockers.length ? null : h('div', null,
        h('label', { class: 'check' }, ack1, h('span', null, `تأیید می‌کنم «${symName(d)}» (${d.symbol}) همان دارایی من است.`)),
        ack2 ? h('label', { class: 'check' }, ack2, h('span', null, `قیمت این نماد «هر ${unitName(d.unit)}» است؛ مقدار دارایی من در تراکنش‌ها با همین واحد ثبت می‌شود.`)) : null,
        d.status !== 'valid' ? notice('اتصال ممکن است، اما تا زمانی که وضعیت قیمت «معتبر» نشود در ارزش‌گذاری استفاده نمی‌شود.', 'warn') : null));
      sync();
      pane.scrollIntoView({ block: 'nearest' });
    } catch (e) { clear(pane).append(notice(e.message, 'bad')); }
  };
  input.addEventListener('input', debounce(search, 300));
  compat.addEventListener('change', search);
  const m = modal({ title: 'انتخاب نماد از بازار جامع ایران', wide: true, body: [
    h('p', { class: 'muted', style: { marginTop: 0 } }, 'برای هر دارایی فقط یک نماد انتخاب می‌شود. نمادها هرگز خودکار به دارایی‌ها وصل نمی‌شوند.'),
    h('div', { class: 'inline-form', style: { marginBottom: '8px' } }, input,
      currency ? h('label', { class: 'check' }, compat, h('span', null, `فقط نمادهای سازگار با ${currency}`)) : null),
    results, pane], footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), confirmBtn] });
  setTimeout(() => input.focus(), 250);
  search();
  return m;
}
