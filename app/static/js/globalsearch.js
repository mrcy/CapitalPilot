// جست‌وجوی سراسری بازار (پالت جست‌وجو) — نسخهٔ ۲٫۴
// از هر صفحه با کادر نوار بالا، Ctrl+K / ⌘K باز می‌شود و Escape آن را می‌بندد. فقط از دادهٔ ذخیره‌شدهٔ Backend (دیتابیس) می‌خواند؛
// مرورگر هرگز مستقیم به منبع بازار وصل نمی‌شود و برای هر حرف درخواست نمی‌فرستد (Debounce). هیچ عملیاتی بدون تأیید صریح کاربر انجام نمی‌شود.
import { api } from './api.js';
import { badge, clear, h, icon, modal, notice, toast } from './ui.js';
import { debounce } from './listkit.js';
import { state } from './state.js';
import { lineConfig, COLORS } from './charts.js';
import { CATEGORY_LABEL, currencyLabel, fmtDateTime, num, pnlClass, signedPct, unitName, units } from './format.js';

export const GROUPS = [['all', 'همه'], ['mine', 'دارایی‌های من'], ['currency', 'ارز'], ['gold_coin', 'طلا و سکه'], ['funds', 'صندوق‌ها'],
  ['bourse', 'بورس'], ['crypto', 'رمزارز'], ['commodity_energy', 'کالا و انرژی'], ['other', 'سایر موارد']];
const TYPE_BY_GROUP = { currency: 'currency', gold_coin: 'gold', funds: 'fund', bourse: 'index', crypto: 'digital', commodity_energy: 'commodity', other: 'other' };
const STATUS_KIND = { valid: 'ok', stale: 'warn', invalid: 'bad', missing: '' };
const STATUS_TEXT = { valid: 'معتبر', stale: 'قدیمی', invalid: 'نامعتبر', missing: 'ناموجود' };
const KIND_ICON = { symbol: 'price', asset: 'assets', platform: 'platform', market: 'globe' };
const KIND_LABEL = { symbol: 'نماد بازار', asset: 'دارایی من', platform: 'پلتفرم', market: 'بازار' };
const RECENT_KEY = 'cp.gs.recent';
const MAX_RECENT = 8;
const PAGE = 30;
const DEBOUNCE_MS = 250;

const ltr = (t, cls = '') => h('span', { dir: 'ltr', class: `ltr-text ${cls}`.trim() }, t);
const isMac = /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || '');
const real = (name, sym) => (name && name !== sym ? name : '');
const nameOf = (it) => real(it.name_fa, it.symbol) || real(it.name_en, it.symbol) || it.symbol || it.name_fa || '';
const priceText = (it) => {
  if (it.price === null || it.price === undefined) return null;
  const n = Number(it.price);
  const body = it.currency === 'IRT' || it.currency === 'IRR' ? num(n, n < 100 ? 2 : 0) : units(n);
  return `${body} ${currencyLabel(it.currency)}`;
};
const loadRecent = () => { try { const v = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string').slice(0, MAX_RECENT) : []; } catch { return []; } };
const saveRecent = (q) => {
  const t = (q || '').trim();
  if (t.length < 2) return;
  const list = [t, ...loadRecent().filter((x) => x !== t)].slice(0, MAX_RECENT);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* حافظه پر یا غیرفعال */ }
};
export const clearRecent = () => { try { localStorage.removeItem(RECENT_KEY); } catch { /* ignore */ } };
export const recentSearches = loadRecent;

let ui = null;
let trigger = null;
let lastFocus = null;
const st = { open: false, q: '', group: 'all', seq: 0, data: null, view: 'list', active: -1, page: 1, suspended: false, suggestions: null, sugAt: 0, charts: [], cache: new Map(), detail: null };

// ---------------------------------------------------------------- ساخت پالت
function build() {
  const input = h('input', { type: 'search', class: 'gs-input', placeholder: 'جست‌وجو در نمادها، ارزها، طلا و سکه، رمزارزها، دارایی‌ها…', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
    enterkeyhint: 'search', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'gs-list', 'aria-autocomplete': 'list', 'aria-label': 'جست‌وجوی سراسری بازار', 'data-testid': 'gs-input' });
  const spinner = h('div', { class: 'spinner gs-spin', hidden: true, 'aria-hidden': 'true' });
  const closeBtn = h('button', { class: 'icon-btn gs-close', type: 'button', 'aria-label': 'بستن جست‌وجو', 'data-testid': 'gs-close', onclick: () => closeSearch() }, icon('close', 20));
  const head = h('div', { class: 'gs-head' }, h('span', { class: 'gs-head-ico' }, icon('search', 20)), input, spinner, h('kbd', { class: 'kbd gs-esc' }, 'Esc'), closeBtn);
  const chips = h('div', { class: 'gs-chips', role: 'toolbar', 'aria-label': 'فیلتر دسته‌بندی نتایج', 'data-testid': 'gs-chips' },
    GROUPS.map(([k, label]) => h('button', { class: `gs-chip ${k === 'all' ? 'active' : ''}`, type: 'button', 'data-group': k, 'aria-pressed': k === 'all' ? 'true' : 'false', 'data-testid': `gs-chip-${k}`,
      onclick: () => setGroup(k) }, h('span', null, label), h('small', { class: 'gs-count' }))));
  const banner = h('div', { class: 'gs-banner', 'data-testid': 'gs-banner', hidden: true });
  const list = h('div', { class: 'gs-list', id: 'gs-list', role: 'listbox', 'aria-label': 'نتایج جست‌وجو', 'data-testid': 'gs-list' });
  const detail = h('div', { class: 'gs-detail', 'data-testid': 'gs-detail', hidden: true });
  const foot = h('div', { class: 'gs-foot' },
    h('span', null, 'کلیدهای جهت‌دار: حرکت'),
    h('span', null, h('kbd', { class: 'kbd' }, 'Enter'), ' انتخاب'),
    h('span', null, h('kbd', { class: 'kbd' }, 'Esc'), ' بستن'),
    h('span', { class: 'gs-foot-note' }, 'جست‌وجو فقط روی دادهٔ ذخیره‌شده است و هیچ سفارش یا تراکنشی ثبت نمی‌کند.'));
  const panel = h('div', { class: 'gs-panel', tabindex: '-1', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'جست‌وجوی سراسری بازار', 'data-testid': 'gs-panel' }, head, chips, banner, list, detail, foot);
  const overlay = h('div', { class: 'gs-overlay', 'data-testid': 'gs-overlay', hidden: true }, panel);
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) closeSearch(); });
  input.addEventListener('input', () => { st.q = input.value; debouncedRun(); });
  panel.addEventListener('keydown', onPanelKey);
  document.body.append(overlay);
  ui = { overlay, panel, input, spinner, chips, banner, list, detail };
}

export function initGlobalSearch() {
  trigger = document.getElementById('gs-trigger');
  if (trigger) {
    clear(trigger).append(h('span', { class: 'gs-trigger-ico' }, icon('search', 18)), h('span', { class: 'gs-trigger-text' }, 'جست‌وجوی سراسری بازار…'),
      h('kbd', { class: 'kbd gs-trigger-kbd' }, isMac ? '⌘ K' : 'Ctrl K'));
    trigger.setAttribute('aria-keyshortcuts', 'Control+K Meta+K');
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.addEventListener('click', () => openSearch());
  }
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && st.open && !st.suspended) { e.preventDefault(); closeSearch(); return; }
    const isK = (e.key && e.key.toLowerCase() === 'k') || e.code === 'KeyK';   // روی چیدمان فارسی هم همان کلید فیزیکی
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && isK) {
      if (st.suspended) return;
      e.preventDefault();
      st.open ? closeSearch() : openSearch();
    }
  });
  window.addEventListener('hashchange', () => { if (st.open && !st.suspended) closeSearch(false); });
}

export function openSearch(prefill) {
  if (st.open) { ui.input.focus(); return; }
  if (!ui) build();
  lastFocus = document.activeElement;
  st.open = true;
  ui.overlay.hidden = false;
  document.body.classList.add('gs-lock');
  trigger?.setAttribute('aria-expanded', 'true');
  // هر بار باز شدن با کادر خالی شروع می‌شود تا جست‌وجوهای اخیر و محبوب دیده شوند
  ui.input.value = typeof prefill === 'string' ? prefill : '';
  st.q = ui.input.value;
  showList();
  run(true);
  loadSuggestions();
  // فوکوس مستقیم روی کادر جست‌وجو
  ui.input.focus();
  requestAnimationFrame(() => { if (st.open && !st.suspended && document.activeElement !== ui.input && !ui.panel.contains(document.activeElement)) ui.input.focus(); });
}

export function closeSearch(restoreFocus = true) {
  if (!st.open) return;
  st.open = false;
  st.suspended = false;
  st.seq++;
  disposeCharts();
  ui.overlay.hidden = true;
  document.body.classList.remove('gs-lock');
  trigger?.setAttribute('aria-expanded', 'false');
  if (restoreFocus && lastFocus && document.contains(lastFocus)) lastFocus.focus();
  else if (restoreFocus) trigger?.focus();
}

// ---------------------------------------------------------------- صفحه‌کلید
function focusables() {
  return [...ui.panel.querySelectorAll('button:not([disabled]), input, select, a[href]')].filter((el) => el.offsetParent !== null);
}
function navItems() { return [...ui.list.querySelectorAll('[data-nav]')]; }
function setActive(i, scroll = true) {
  const items = navItems();
  items.forEach((el) => { el.classList.remove('active'); el.setAttribute('aria-selected', 'false'); });
  st.active = items.length ? Math.max(0, Math.min(i, items.length - 1)) : -1;
  const el = items[st.active];
  if (el) {
    el.classList.add('active');
    el.setAttribute('aria-selected', 'true');
    ui.input.setAttribute('aria-activedescendant', el.id);
    if (scroll) el.scrollIntoView({ block: 'nearest' });
  } else ui.input.removeAttribute('aria-activedescendant');
}
function onPanelKey(e) {
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeSearch(); return; }
  if (e.key === 'Tab') {
    const f = focusables();
    if (!f.length) return;
    const first = f[0]; const last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    return;
  }
  if (st.view !== 'list') return;
  const inInput = document.activeElement === ui.input;
  if (e.key === 'ArrowDown') { e.preventDefault(); setActive(st.active + 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(st.active <= 0 ? 0 : st.active - 1); if (st.active === 0 && inInput) ui.list.scrollTop = 0; }
  else if (e.key === 'Home' && !inInput) { e.preventDefault(); setActive(0); }
  else if (e.key === 'End' && !inInput) { e.preventDefault(); setActive(navItems().length - 1); }
  else if (e.key === 'Enter' && inInput) {
    const el = navItems()[st.active];
    if (el) { e.preventDefault(); el.click(); }
    else { e.preventDefault(); run(true); saveRecent(ui.input.value); }
  }
}

// ---------------------------------------------------------------- جست‌وجو
function setGroup(k) {
  st.group = k; st.page = 1;
  ui.chips.querySelectorAll('.gs-chip').forEach((b) => { const on = b.dataset.group === k; b.classList.toggle('active', on); b.setAttribute('aria-pressed', String(on)); });
  showList();
  run(true);
}
const debouncedRun = debounce(() => run(), DEBOUNCE_MS);
function showList() {
  st.view = 'list';
  disposeCharts();
  ui.detail.hidden = true;
  ui.list.hidden = false;
  ui.chips.hidden = false;
}

async function run(immediate = false) {
  const q = ui.input.value.trim();
  st.q = q;
  const my = ++st.seq;
  if (!q) { renderIdle(); return; }
  ui.spinner.hidden = false;
  if (immediate || !st.data) clear(ui.list).append(stateBox('loading'));
  try {
    const data = await api.get('/api/search', { q, group: st.group, page: 1, page_size: PAGE, per_group: 5 }, { silent: true });
    if (my !== st.seq || !st.open) return;
    st.data = data; st.page = 1;
    renderResults(data);
  } catch (e) {
    if (my !== st.seq || !st.open) return;
    clear(ui.list).append(stateBox('error', e.message || 'جست‌وجو ناموفق بود.'));
    setBanner(null);
  } finally {
    if (my === st.seq) ui.spinner.hidden = true;
  }
}

function stateBox(kind, message) {
  if (kind === 'loading') return h('div', { class: 'gs-state', 'data-testid': 'gs-state-loading', role: 'status' }, h('div', { class: 'spinner' }), h('span', null, 'در حال جست‌وجو…'));
  if (kind === 'error') {
    return h('div', { class: 'gs-state', 'data-testid': 'gs-state-error', role: 'alert' }, icon('alert', 26), h('b', null, 'جست‌وجو انجام نشد'), h('span', { class: 'muted' }, message),
      h('button', { class: 'btn', type: 'button', onclick: () => run(true) }, icon('refresh', 15), 'تلاش دوباره'));
  }
  return h('div', { class: 'gs-state', 'data-testid': 'gs-state-empty' }, icon('search', 26), h('b', null, message || 'نتیجه‌ای پیدا نشد'),
    h('span', { class: 'muted' }, 'نام فارسی یا انگلیسی، نماد (مثل BTC) یا بخشی از آن را امتحان کنید. جست‌وجو به تفاوت «ی/ي» و «ک/ك» و اعداد فارسی/انگلیسی حساس نیست.'));
}

function setBanner(ds, data) {
  const b = ui.banner;
  const msgs = [];
  if (ds) {
    if (!ds.has_data) msgs.push(['warn', 'داده‌های بازار هنوز دریافت نشده است؛ فقط دارایی‌ها، پلتفرم‌ها و بازارهای ثبت‌شده جست‌وجو می‌شوند. برای نمادهای بازار، در «بازار جامع ایران» منبع را فعال و دریافت کنید.']);
    else if (ds.stale) msgs.push(['warn', `داده‌های بازار قدیمی‌اند${ds.fetch_age_minutes != null ? ` (آخرین دریافت ${ageText(ds.fetch_age_minutes)})` : ''}؛ جست‌وجو روی آخرین داده‌های ذخیره‌شده انجام می‌شود و قیمت‌ها «زنده» نیستند.`]);
  }
  if (navigator.onLine === false) msgs.push(['info', 'اینترنت قطع است؛ جست‌وجو همچنان روی آخرین داده‌های ذخیره‌شده کار می‌کند.']);
  if (data?.fuzzy) msgs.push(['info', 'تطبیق دقیقی پیدا نشد؛ نتایج بر اساس شباهت (غلط املایی احتمالی) نمایش داده می‌شوند.']);
  clear(b);
  b.hidden = !msgs.length;
  msgs.forEach(([k, t]) => b.append(h('div', { class: `gs-note ${k}` }, icon(k === 'warn' ? 'alert' : 'info', 15), h('span', null, t))));
}
const ageText = (m) => (m < 1 ? 'هم‌اکنون' : m < 60 ? `${num(m)} دقیقه پیش` : m < 1440 ? `${num(Math.floor(m / 60))} ساعت پیش` : `${num(Math.floor(m / 1440))} روز پیش`);

function updateCounts(counts) {
  ui.chips.querySelectorAll('.gs-chip').forEach((b) => {
    const n = counts ? counts[b.dataset.group] : null;
    b.querySelector('.gs-count').textContent = n === null || n === undefined ? '' : num(n);
    b.classList.toggle('empty', n === 0);
  });
}

function renderResults(data) {
  updateCounts(data.counts);
  setBanner(data.data_state, data);
  const box = clear(ui.list);
  ui.list.dataset.q = st.q; ui.list.dataset.total = String(data.total);
  let n = 0;
  const nextId = () => `gs-opt-${n++}`;
  if (data.group === 'all') {
    if (!data.groups.length) box.append(stateBox('empty'));
    data.groups.forEach((g) => {
      const sec = h('section', { class: 'gs-section', 'data-testid': `gs-section-${g.key}` },
        h('header', { class: 'gs-sec-head' }, h('b', null, g.label), h('small', { class: 'muted' }, `${num(g.total)} نتیجه`),
          g.total > g.items.length ? h('button', { class: 'btn tiny ghost', type: 'button', 'data-testid': `gs-all-${g.key}`, onclick: () => setGroup(g.key) }, `مشاهدهٔ همهٔ ${num(g.total)} نتیجه`, icon('chevron', 13)) : null));
      g.items.forEach((it) => sec.append(rowEl(it, nextId())));
      box.append(sec);
    });
  } else {
    if (!data.items.length) box.append(stateBox('empty'));
    else {
      const sec = h('section', { class: 'gs-section' }, h('header', { class: 'gs-sec-head' }, h('b', null, GROUPS.find((x) => x[0] === data.group)?.[1] || ''), h('small', { class: 'muted', 'data-testid': 'gs-total' }, `${num(data.total)} نتیجه`)));
      data.items.forEach((it) => sec.append(rowEl(it, nextId())));
      box.append(sec);
      addMore(box, data, sec);
    }
  }
  setActive(navItems().length ? 0 : -1, false);
  ui.list.scrollTop = 0;
}

function addMore(box, data, sec) {
  const shown = sec.querySelectorAll('.gs-row').length;
  box.querySelector('.gs-more')?.remove();
  if (shown >= data.total) return;
  box.append(h('button', { class: 'btn gs-more', type: 'button', 'data-testid': 'gs-more', onclick: async (e) => {
    const btn = e.currentTarget; btn.disabled = true;
    try {
      const my = st.seq;
      const d = await api.get('/api/search', { q: st.q, group: data.group, page: st.page + 1, page_size: PAGE }, { silent: true });
      if (my !== st.seq) return;
      st.page += 1;
      let n = navItems().length;
      d.items.forEach((it) => sec.append(rowEl(it, `gs-opt-${n++}`)));
      addMore(box, data, sec);
    } catch (err) { toast(err.message, 'error'); btn.disabled = false; }
  } }, `نمایش بیشتر (${num(shown)} از ${num(data.total)})`));
}

// ---------------------------------------------------------------- ردیف نتیجه
function statusChip(it) {
  if (!it.status) return null;
  return h('span', { class: `badge ${STATUS_KIND[it.status] || ''} gs-st gs-st-${it.status}`, 'data-testid': 'gs-status', 'data-status': it.status, title: it.status_reason || '' }, it.status === 'valid' && it.warning ? 'معتبر با هشدار' : STATUS_TEXT[it.status]);
}

function rowEl(it, id) {
  const price = priceText(it);
  const dim = it.status && it.status !== 'valid';
  const sub = [it.symbol ? ltr(it.symbol, 'gs-sym') : null, it.category_label || null, it.market_label || null, it.platform ? `پلتفرم ${it.platform}` : null].filter(Boolean);
  const subEls = sub.flatMap((x, i) => (i ? [h('i', { class: 'gs-dot' }, '·'), x] : [x]));
  const links = (it.linked_assets || []);
  const tags = [
    it.kind === 'asset' ? badge('دارایی من', 'gold') : null,
    links.length ? badge(`متصل به ${links[0].name}`, 'blue') : null,
    it.match === 'fuzzy' ? badge('تطبیق تقریبی', 'info') : null,
    it.kind === 'platform' ? badge(`${num(it.asset_count || 0)} دارایی`, '') : null,
    it.kind === 'market' ? badge(`${num(it.count || 0)} مورد`, '') : null,
  ].filter(Boolean);
  const priceBox = it.status
    ? h('span', { class: `gs-price ${dim ? 'dim' : ''}`, 'data-testid': 'gs-price' },
      price ? h('b', { class: 'gs-price-val' }, price) : h('b', { class: 'gs-price-val muted' }, '—'),
      it.change_pct !== null && it.change_pct !== undefined ? h('small', { class: `gs-chg ${pnlClass(it.change_pct)}` }, signedPct(it.change_pct)) : null,
      h('small', { class: 'muted gs-src' }, [it.source, it.age_text].filter(Boolean).join(' · ') || (it.status === 'missing' ? 'قیمتی ثبت نشده' : '')))
    : null;
  const stale = it.status === 'stale' ? h('span', { class: 'gs-warn', 'data-testid': 'gs-stale-warning' }, icon('alert', 13), 'قیمت قدیمی؛ زنده نیست') : null;
  const el = h('button', { class: `gs-row kind-${it.kind} st-${it.status || 'none'}`, type: 'button', id, role: 'option', 'aria-selected': 'false', 'data-nav': '1', 'data-testid': 'gs-row', 'data-kind': it.kind, 'data-symbol': it.symbol || '', 'data-id': it.id,
    onclick: () => openDetail(it), onmousemove: () => { const i = navItems().indexOf(el); if (i >= 0 && i !== st.active) setActive(i, false); } },
  h('span', { class: `gs-ico k-${it.kind}` }, icon(KIND_ICON[it.kind] || 'search', 18)),
  h('span', { class: 'gs-main' },
    h('span', { class: 'gs-name' }, h('b', null, nameOf(it)), real(it.name_en, it.symbol) && real(it.name_en, it.symbol) !== nameOf(it) ? ltr(it.name_en, 'gs-en') : null),
    h('span', { class: 'gs-sub' }, subEls),
    tags.length || stale ? h('span', { class: 'gs-tags' }, tags, stale) : null),
  priceBox,
  it.status ? h('span', { class: 'gs-stcol' }, statusChip(it)) : h('span', { class: 'gs-stcol muted' }, h('small', null, KIND_LABEL[it.kind])));
  return el;
}

// ---------------------------------------------------------------- حالت بدون عبارت: اخیر + محبوب
function chipBtn(text, onclick, testid, nav = true) {
  return h('button', { class: 'gs-term', type: 'button', onclick, 'data-testid': testid, ...(nav ? { 'data-nav': '1', role: 'option', 'aria-selected': 'false' } : {}) }, text);
}
async function loadSuggestions() {
  if (st.suggestions && Date.now() - st.sugAt < 60_000) return;
  try {
    st.suggestions = await api.get('/api/search/suggestions', undefined, { silent: true });
    st.sugAt = Date.now();
    if (st.open && !ui.input.value.trim()) renderIdle();
  } catch { /* پیشنهادها اختیاری‌اند */ }
}
function useQuery(q) { ui.input.value = q; st.q = q; ui.input.focus(); saveRecent(q); run(true); }

function renderIdle() {
  updateCounts(null);
  setBanner(st.suggestions?.data_state || null);
  const box = clear(ui.list);
  delete ui.list.dataset.q;
  let n = 0;
  const idn = () => `gs-opt-${n++}`;
  const recents = loadRecent();
  if (recents.length) {
    box.append(h('section', { class: 'gs-section', 'data-testid': 'gs-recent' },
      h('header', { class: 'gs-sec-head' }, h('b', null, 'جست‌وجوهای اخیر'),
        h('button', { class: 'btn tiny ghost', type: 'button', 'data-testid': 'gs-clear-recent', onclick: () => { clearRecent(); toast('تاریخچهٔ جست‌وجو پاک شد.', 'success'); renderIdle(); } }, icon('trash', 13), 'پاک‌کردن تاریخچه')),
      h('div', { class: 'gs-terms' }, recents.map((q) => { const b = chipBtn(h('span', { class: 'gs-term-in' }, icon('refresh', 13), q), () => useQuery(q), 'gs-recent-item'); b.id = idn(); return b; }))));
  }
  const s = st.suggestions;
  if (s && s.popular_terms.length) {
    box.append(h('section', { class: 'gs-section', 'data-testid': 'gs-popular' },
      h('header', { class: 'gs-sec-head' }, h('b', null, 'جست‌وجوهای محبوب'), h('small', { class: 'muted' }, 'فقط عبارت‌هایی که در داده‌های فعلی نتیجه دارند')),
      h('div', { class: 'gs-terms' }, s.popular_terms.map((q) => { const b = chipBtn(q, () => useQuery(q), 'gs-popular-term'); b.id = idn(); return b; }))));
  }
  if (s && s.popular_symbols.length) {
    const sec = h('section', { class: 'gs-section', 'data-testid': 'gs-popular-symbols' }, h('header', { class: 'gs-sec-head' }, h('b', null, 'نمادهای پرکاربرد و نمادهای متصل به دارایی‌های من')));
    s.popular_symbols.slice(0, 8).forEach((it) => sec.append(rowEl({ ...it, kind: 'symbol', id: `sym:${it.symbol}` }, idn())));
    box.append(sec);
  }
  if (!box.childNodes.length) box.append(h('div', { class: 'gs-state', 'data-testid': 'gs-state-start' }, icon('search', 26), h('b', null, 'نام یا نماد را بنویسید'),
    h('span', { class: 'muted' }, 'مثلاً «طلای ۱۸»، «دلار»، «bitcoin» یا «BTC». نتایج از دادهٔ ذخیره‌شدهٔ برنامه خوانده می‌شوند.')));
  setActive(navItems().length ? 0 : -1, false);
}

// ---------------------------------------------------------------- نمودار
function disposeCharts() { st.charts.forEach((c) => { try { c.destroy(); } catch { /* ignore */ } }); st.charts = []; }
function drawChart(box, cfg) {
  clear(box);
  if (!cfg || !window.Chart) { box.append(h('div', { class: 'chart-empty' }, 'داده‌ای برای نمایش وجود ندارد.')); return; }
  const canvas = h('canvas');
  box.append(canvas);
  st.charts.push(new window.Chart(canvas, cfg));
}

// ---------------------------------------------------------------- پنل جزئیات
const kv = (l, v) => h('div', null, h('span', null, l), h('b', null, v ?? '—'));
function suspendFor(cfg) {
  st.suspended = true;
  ui.overlay.hidden = true;
  const m = modal({ ...cfg, onClose: () => { st.suspended = false; if (st.open) { ui.overlay.hidden = false; (cfg.restoreFocus || ui.panel.querySelector('.gs-actions button') || ui.input)?.focus?.(); } cfg.onClose?.(); } });
  return m;
}
async function refreshPage() { try { (await import('./app.js')).reload(); } catch { /* صفحهٔ جاری بازسازی نشد */ } }

async function openDetail(it) {
  if (it.kind === 'market') { useQuery(it.name_fa); return; }
  saveRecent(st.q);
  st.view = 'detail'; st.detail = it;
  ui.list.hidden = true; ui.chips.hidden = true;
  ui.detail.hidden = false;
  clear(ui.detail).append(stateBox('loading'));
  try {
    if (it.kind === 'symbol') await detailSymbol(it);
    else if (it.kind === 'asset') await detailAsset(it);
    else await detailPlatform(it);
  } catch (e) {
    if (st.view !== 'detail') return;
    clear(ui.detail).append(detailHead(it), stateBox('error', e.message));
  }
  ui.detail.querySelector('.gs-back')?.focus();
}

function backToList() { showList(); const el = ui.list.querySelector(`[data-id="${CSS.escape(st.detail?.id || '')}"]`); if (el) { setActive(navItems().indexOf(el), true); el.focus(); } else ui.input.focus(); }

function detailHead(it, d) {
  const src = d || it;
  return h('header', { class: 'gs-dhead' },
    h('button', { class: 'btn ghost tiny gs-back', type: 'button', 'data-testid': 'gs-back', onclick: backToList }, icon('back', 14), 'بازگشت به نتایج'),
    h('div', { class: 'gs-dtitle' }, h('h3', null, nameOf(src)), h('div', { class: 'gs-dsub' }, real(src.name_en, src.symbol) && real(src.name_en, src.symbol) !== nameOf(src) ? ltr(src.name_en) : null, src.symbol ? ltr(src.symbol, 'gs-sym') : null,
      it.category_label ? badge(it.category_label, 'info') : null, it.market_label ? badge(it.market_label, '') : null, statusChip(it))));
}

function tabs(defs, panelBox) {
  const bar = h('div', { class: 'gs-tabs', role: 'tablist', 'aria-label': 'بخش‌های جزئیات' });
  const btns = defs.map(([key, label, loader]) => {
    const b = h('button', { class: 'gs-tab', type: 'button', role: 'tab', 'aria-selected': 'false', 'data-testid': `gs-tab-${key}`, onclick: () => select(key) }, label);
    b.dataset.key = key;
    return b;
  });
  bar.append(...btns);
  async function select(key) {
    btns.forEach((b) => { const on = b.dataset.key === key; b.classList.toggle('active', on); b.setAttribute('aria-selected', String(on)); });
    disposeCharts();
    clear(panelBox).append(h('div', { class: 'gs-state' }, h('div', { class: 'spinner' })));
    try { const body = await defs.find((x) => x[0] === key)[2](); if (st.view === 'detail') clear(panelBox).append(body); }
    catch (e) { clear(panelBox).append(notice(e.message || 'بارگذاری ناموفق بود.', 'bad')); }
  }
  bar.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const n = btns[(i + (e.key === 'ArrowLeft' ? 1 : -1) + btns.length) % btns.length];   // RTL: راست = قبلی
    n.focus(); n.click();
  });
  return { bar, select };
}

function priceBlock(it, d) {
  const price = priceText(it);   // فقط قیمتی که جست‌وجو مجاز می‌داند (معتبر/قدیمی)؛ قیمت نامعتبر هرگز نمایش داده نمی‌شود
  const live = it.status === 'valid';
  const chg = it.change_pct;
  return h('div', { class: `gs-pricebox ${live ? '' : 'dim'}`, 'data-testid': 'gs-detail-price' },
    h('div', { class: 'gs-bigprice' }, price ? h('b', null, price) : h('b', { class: 'muted' }, 'قیمت معتبری وجود ندارد'),
      chg !== null && chg !== undefined ? h('span', { class: `gs-chg ${pnlClass(chg)}` }, signedPct(chg)) : null, statusChip(it)),
    h('div', { class: 'muted gs-meta' }, [it.price_time ? `زمان قیمت: ${fmtDateTime(it.price_time)}` : null, it.age_text, it.source ? `منبع: ${it.source}` : null].filter(Boolean).join(' · ') || 'بدون زمان ثبت‌شده'),
    !live && it.status ? notice(it.status === 'stale' ? `قیمت قدیمی است و «زنده» نیست؛ در ارزش‌گذاری استفاده نمی‌شود. ${it.status_reason || ''}` : `این قیمت قابل استفاده نیست و در ارزش‌گذاری به کار نمی‌رود. ${it.status_reason || ''}`, it.status === 'stale' ? 'warn' : 'bad') : null);
}

function actionBar(buttons) { return h('footer', { class: 'gs-actions', 'data-testid': 'gs-actions' }, buttons.filter(Boolean)); }
function actBtn(label, ic, onclick, { primary = false, testid, disabled = false, title } = {}) {
  return h('button', { class: `btn ${primary ? 'primary' : ''}`, type: 'button', onclick, disabled: disabled || null, title: title || null, 'data-testid': testid }, icon(ic, 15), label);
}

// ---- نماد بازار
async function detailSymbol(it) {
  const d = await api.get(`/api/iran-market/symbols/${encodeURIComponent(it.symbol)}`, undefined, { silent: true });
  if (st.view !== 'detail' || st.detail !== it) return;
  const live = (d.linked_assets || []).filter((a) => !a.is_archived);
  const blockers = d.link_blockers || [];
  const body = h('div', { class: 'gs-dbody' }, priceBlock(it, d));
  const panelBox = h('div', { class: 'gs-tabpanel', role: 'tabpanel', 'data-testid': 'gs-tabpanel' });
  const T = tabs([
    ['summary', 'خلاصه', async () => summarySymbol(it, d)],
    ['chart', 'نمودار قیمت', () => chartSymbol(it, d)],
    ['history', 'تاریخچهٔ قیمت', () => historySymbol(it, d)],
    ['source', 'منبع قیمت', async () => sourceSymbol(it, d)],
  ], panelBox);
  const linkInfo = live.length
    ? h('div', { class: 'gs-linkinfo', 'data-testid': 'gs-link-status' }, icon('link', 15), h('span', null, 'این نماد از قبل به دارایی '), ...live.flatMap((a, i) => [i ? '، ' : null, h('a', { href: `#/assets/${a.asset_id}`, onclick: () => closeSearch(false) }, `«${a.name}»`)]), h('span', null, ' متصل است؛ اتصال تکراری ممکن نیست.'))
    : null;
  const blockNote = !live.length && blockers.length ? blockers.map((b) => notice(`اتصال/ایجاد دارایی ممکن نیست: ${b}`, 'info')) : null;
  const cannot = live.length > 0 || blockers.length > 0;
  clear(ui.detail).append(...[detailHead(it, d), body, linkInfo, ...(blockNote || []), T.bar, panelBox,
    actionBar([
      actBtn('مشاهدهٔ جزئیات کامل نماد', 'globe', () => { closeSearch(false); location.hash = `#/iran-market/s/${encodeURIComponent(it.symbol)}`; }, { testid: 'gs-action-open' }),
      actBtn('اتصال به دارایی موجود', 'link', () => linkModal(it, d), { primary: !cannot, testid: 'gs-action-link', disabled: cannot, title: cannot ? (live.length ? 'این نماد از قبل متصل است.' : blockers[0]) : '' }),
      actBtn('ایجاد دارایی جدید از روی نماد', 'plus', () => createModal(it, d, false), { testid: 'gs-action-create', disabled: cannot, title: cannot ? (live.length ? 'این نماد از قبل به یک دارایی متصل است.' : blockers[0]) : '' }),
      actBtn('افزودن به سبد', 'portfolio', () => (live.length ? portfolioModal({ id: live[0].asset_id, name: live[0].name }) : createModal(it, d, true)), { testid: 'gs-action-portfolio', disabled: !live.length && blockers.length > 0, title: !live.length && blockers.length ? blockers[0] : '' }),
    ])].filter(Boolean));
  T.select('summary');
}

function summarySymbol(it, d) {
  const trusted = it.status === 'valid' || it.status === 'stale';
  const num2 = (v) => (!trusted || v === null || v === undefined ? '—' : d.currency === 'IRT' ? num(v, 2) : units(v));
  return h('div', { class: 'kv kv-3 gs-kv' },
    kv('نماد', ltr(d.symbol)), kv('دسته', CATEGORY_LABEL[d.category]), kv('بازار', it.market_label || '—'), kv('واحد پول', `${currencyLabel(d.currency)}${d.currency ? ` (${d.currency})` : ''}`),
    kv('واحد قیمت', `${unitName(d.unit)} (اندازه ${num(d.unit_size)})`), kv('باز', num2(d.open)), kv('بالا', num2(d.high)), kv('پایین', num2(d.low)),
    kv('قیمت پایانی قبل', num2(d.prev_close)), kv('تغییر', num2(d.change)), kv('وضعیت بازار', d.market_status || '—'), kv('گروه', it.group_label || '—'));
}

async function chartSymbol(it, d) {
  const box = h('div', { class: 'gs-chartbox' });
  const wrap = h('div', null, h('div', { class: 'gs-chart-note muted', 'data-testid': 'gs-chart-note' }), box);
  const hist = await getHistory(it.symbol);
  if (hist.available && hist.points.length > 1) {
    const pts = hist.points.map((x) => ({ date: String(x.t).slice(0, 10), close: x.close }));
    wrap.firstChild.textContent = `تاریخچهٔ روزانه (${num(pts.length)} روز آخر، ${currencyLabel(hist.currency || d.currency)}) — منبع: فایل‌های تاریخچهٔ Iran Market Data`;
    queueMicrotask(() => drawChart(box, lineConfig(pts, [{ key: 'close', label: 'قیمت پایانی', color: COLORS.blue, fill: 'rgba(74,163,255,.10)' }])));
    return wrap;
  }
  const stored = await getStored(it.symbol);
  if (stored.items.length > 1) {
    const pts = [...stored.items].reverse().map((x) => ({ date: x.recorded_at, price: x.price }));
    wrap.firstChild.textContent = 'تاریخچهٔ آنلاین در دسترس نیست؛ قیمت‌های ذخیره‌شده در CapitalPilot برای دارایی‌های متصل نمایش داده می‌شود.';
    queueMicrotask(() => drawChart(box, lineConfig(pts, [{ key: 'price', label: 'قیمت', color: COLORS.gold }])));
    return wrap;
  }
  return h('div', null, notice(`${hist.message || 'تاریخچه‌ای در دسترس نیست.'} نمودار فقط وقتی کشیده می‌شود که حداقل دو قیمت واقعی موجود باشد؛ آخرین قیمت ذخیره‌شده در بخش «خلاصه» دیده می‌شود.`, 'info'));
}
async function getHistory(sym) {
  const k = `h:${sym}`;
  if (!st.cache.has(k)) st.cache.set(k, await api.get(`/api/iran-market/symbols/${encodeURIComponent(sym)}/history`, { days: 180 }, { silent: true }).catch((e) => ({ available: false, points: [], message: e.message })));
  return st.cache.get(k);
}
async function getStored(sym) {
  return api.get(`/api/iran-market/symbols/${encodeURIComponent(sym)}/stored-prices`, undefined, { silent: true }).catch(() => ({ items: [] }));
}
async function historySymbol(it, d) {
  const hist = await getHistory(it.symbol);
  const stored = await getStored(it.symbol);
  const out = h('div', { class: 'gs-hist', 'data-testid': 'gs-history' });
  if (hist.available && hist.points.length) {
    const rows = [...hist.points].reverse().slice(0, 30);
    out.append(h('table', { class: 'data gs-tbl' }, h('thead', null, h('tr', null, ['تاریخ', 'باز', 'بالا', 'پایین', 'پایانی'].map((x) => h('th', null, x)))),
      h('tbody', null, rows.map((p) => h('tr', null, h('td', null, p.date_jalali || String(p.t).slice(0, 10)), ...['open', 'high', 'low', 'close'].map((k) => h('td', { class: 'num' }, p[k] == null ? '—' : units(p[k]))))))));
  } else out.append(notice(hist.message || 'تاریخچهٔ روزانه در دسترس نیست (منبع در دسترس نیست یا اینترنت قطع است).', 'info'));
  if (stored.items.length) {
    out.append(h('h4', { class: 'gs-h4' }, 'قیمت‌های ذخیره‌شده در CapitalPilot'), h('table', { class: 'data gs-tbl' }, h('thead', null, h('tr', null, ['دارایی', 'قیمت', 'زمان قیمت', 'وضعیت'].map((x) => h('th', null, x)))),
      h('tbody', null, stored.items.slice(0, 15).map((x) => h('tr', null, h('td', null, x.asset), h('td', { class: 'num' }, `${num(x.price, 2)} ${currencyLabel(x.currency)}`), h('td', null, fmtDateTime(x.recorded_at)), h('td', null, badge(x.is_valid ? 'معتبر' : 'نامعتبر', x.is_valid ? 'ok' : 'bad')))))));
  } else if (!(hist.available && hist.points.length)) out.append(h('p', { class: 'muted' }, `آخرین قیمت ذخیره‌شده: ${priceText(it) || '—'} ${it.price_time ? `(${fmtDateTime(it.price_time)})` : ''}`));
  return out;
}
function sourceSymbol(it, d) {
  const ds = st.data?.data_state || st.suggestions?.data_state || {};
  return h('div', { class: 'gs-source', 'data-testid': 'gs-source' },
    h('div', { class: 'kv kv-3 gs-kv' }, kv('تأمین‌کننده', 'Iran Market Data'), kv('منبع اصلی قیمت', d.source || '—'), kv('زمان قیمت', d.price_time ? fmtDateTime(d.price_time) : '—'),
      kv('زمان بررسی منبع', d.checked_at ? fmtDateTime(d.checked_at) : '—'), kv('زمان تولید فایل', ds.generated_at ? fmtDateTime(ds.generated_at) : '—'), kv('آخرین دریافت موفق', ds.last_ok_at ? fmtDateTime(ds.last_ok_at) : '—')),
    d.status !== 'valid' && d.status !== 'warning' ? notice(`وضعیت قیمت: ${d.status_reason || STATUS_TEXT[it.status]}`, 'warn') : null,
    (d.quality || []).length ? notice(`پرچم‌های کیفیت منبع: ${d.quality.join('، ')}`, 'warn') : null,
    h('p', { class: 'muted' }, 'داده‌ها متعلق به منبع‌های اصلی‌اند و صرفاً اطلاع‌رسانی هستند. ', h('a', { href: '#/iran-market/health', onclick: () => closeSearch(false) }, 'سلامت دریافت‌ها'), ' · ', h('a', { href: '#/sources', onclick: () => closeSearch(false) }, 'تنظیم منبع')));
}

// ---- دارایی من
async function detailAsset(it) {
  const [d, prices] = await Promise.all([api.get(`/api/assets/${it.asset_id}`, undefined, { silent: true }), api.get('/api/prices', { asset_id: it.asset_id, limit: 120 }, { silent: true })]);
  if (st.view !== 'detail' || st.detail !== it) return;
  const panelBox = h('div', { class: 'gs-tabpanel', role: 'tabpanel', 'data-testid': 'gs-tabpanel' });
  const good = prices.filter((p) => p.is_approved && p.is_valid);
  const T = tabs([
    ['summary', 'خلاصه', async () => h('div', null, h('div', { class: 'kv kv-3 gs-kv' }, kv('نوع', d.asset_type_label), kv('پلتفرم', d.platform), kv('نماد', d.symbol ? ltr(d.symbol) : '—'), kv('واحد قیمت', d.price_currency ? currencyLabel(d.price_currency) : '—'),
      kv('بازار', d.market || '—'), kv('واحد', d.unit), kv('وضعیت', d.status === 'active' ? 'فعال' : d.status === 'archived' ? 'بایگانی' : 'غیرفعال'), kv('وزن هدف', d.target_weight != null ? `${num(d.target_weight, 2)}٪` : '—')),
      h('h4', { class: 'gs-h4' }, 'سبدهای شامل این دارایی'),
      (it.portfolios || []).length ? h('div', { class: 'gs-terms' }, it.portfolios.map((p) => badge(p.name, 'blue'))) : h('p', { class: 'muted' }, 'در هیچ سبدی عضو نیست.'))],
    ['chart', 'نمودار قیمت', async () => {
      if (good.length < 2) return notice('برای کشیدن نمودار حداقل دو قیمت تأییدشدهٔ معتبر لازم است.', 'info');
      const box = h('div', { class: 'gs-chartbox' });
      const pts = [...good].reverse().map((p) => ({ date: p.recorded_at, price: p.price }));
      queueMicrotask(() => drawChart(box, lineConfig(pts, [{ key: 'price', label: 'قیمت', color: COLORS.gold }])));
      return h('div', null, h('div', { class: 'gs-chart-note muted' }, 'قیمت‌های تأییدشدهٔ معتبر ثبت‌شده در CapitalPilot'), box);
    }],
    ['history', 'تاریخچهٔ قیمت', async () => (prices.length ? h('table', { class: 'data gs-tbl', 'data-testid': 'gs-history' }, h('thead', null, h('tr', null, ['زمان', 'قیمت', 'منبع', 'وضعیت'].map((x) => h('th', null, x)))),
      h('tbody', null, prices.slice(0, 30).map((p) => h('tr', null, h('td', null, fmtDateTime(p.recorded_at)), h('td', { class: 'num' }, `${num(p.price, 2)} ${currencyLabel(p.currency)}`), h('td', null, p.source || '—'),
        h('td', null, badge(p.is_valid ? (p.is_approved ? 'معتبر' : 'در انتظار تأیید') : 'نامعتبر', p.is_valid && p.is_approved ? 'ok' : 'warn'))))))
      : notice('هنوز قیمتی برای این دارایی ثبت نشده است.', 'info'))],
    ['source', 'منبع قیمت', async () => (d.sources.length ? h('div', { class: 'gs-source', 'data-testid': 'gs-source' }, h('table', { class: 'data gs-tbl' }, h('thead', null, h('tr', null, ['منبع', 'شناسه', 'اولویت', 'آخرین وضعیت'].map((x) => h('th', null, x)))),
      h('tbody', null, d.sources.map((s) => h('tr', null, h('td', null, s.provider), h('td', null, s.external_id ? ltr(s.external_id) : '—'), h('td', { class: 'num' }, num(s.priority)), h('td', null, s.last_status || '—')))))) : notice('برای این دارایی منبع آنلاین تعریف نشده است؛ قیمت فقط دستی ثبت می‌شود.', 'info'))],
  ], panelBox);
  clear(ui.detail).append(detailHead(it, d), h('div', { class: 'gs-dbody' }, priceBlock(it, null)), T.bar, panelBox,
    actionBar([
      actBtn('مشاهدهٔ دارایی', 'assets', () => { closeSearch(false); location.hash = `#/assets/${it.asset_id}`; }, { primary: true, testid: 'gs-action-open' }),
      actBtn('افزودن به سبد', 'portfolio', () => portfolioModal({ id: it.asset_id, name: d.name }, it.portfolios || []), { testid: 'gs-action-portfolio' }),
    ]));
  T.select('summary');
}

// ---- پلتفرم
async function detailPlatform(it) {
  const res = await api.get('/api/assets', { platform_id: it.platform_id, status: 'live', page_size: 100 }, { silent: true });
  if (st.view !== 'detail' || st.detail !== it) return;
  clear(ui.detail).append(detailHead(it), h('div', { class: 'gs-dbody' },
    h('p', { class: 'muted' }, `پلتفرم ${it.name_fa} — ${num(res.assets.length)} دارایی فعال/غیرفعال`),
    res.assets.length ? h('div', { class: 'gs-terms' }, res.assets.map((a) => h('a', { class: 'gs-term', href: `#/assets/${a.id}`, onclick: () => closeSearch(false) }, a.name))) : notice('هنوز دارایی‌ای در این پلتفرم تعریف نشده است.', 'info')),
  actionBar([actBtn('مدیریت پلتفرم‌ها', 'platform', () => { closeSearch(false); location.hash = '#/platforms'; }, { primary: true, testid: 'gs-action-open' })]));
}

// ---------------------------------------------------------------- مودال‌های عملیات (فقط با تأیید صریح)
const fmtErr = (e) => e?.message || 'عملیات ناموفق بود.';
function selectEl(options, { testid, label, value } = {}) {
  const sel = h('select', { 'aria-label': label, 'data-testid': testid }, options.map((o) => h('option', { value: o.value, disabled: o.disabled || null }, o.label)));
  if (value !== undefined) sel.value = String(value);
  return sel;
}
const fieldRow = (label, el) => h('label', { class: 'gs-field' }, h('span', { class: 'lbl' }, label), el);
function previewCard(it, d) {
  const price = priceText(it);
  return h('div', { class: 'card gs-preview', 'data-testid': 'gs-link-preview' }, h('div', null, h('b', null, nameOf(d.name_fa ? d : it)), ' ', ltr(d.symbol), ' ', statusChip(it)),
    h('div', { class: 'kv kv-3 gs-kv' }, kv('آخرین قیمت', price || '—'), kv('واحد پول', currencyLabel(d.currency)), kv('واحد قیمت', unitName(d.unit)), kv('زمان قیمت', d.price_time ? fmtDateTime(d.price_time) : '—')),
    it.status && it.status !== 'valid' ? notice(`اتصال ممکن است، اما تا وقتی وضعیت قیمت «معتبر» نشود در ارزش‌گذاری استفاده نمی‌شود (${STATUS_TEXT[it.status]}).`, 'warn') : null);
}
const needUnit = (d) => d.unit && d.unit !== 'unit';

async function linkModal(it, d) {
  const portfolios = state.meta.portfolios.filter((p) => !p.is_archived);
  const pSel = selectEl(portfolios.map((p) => ({ value: p.id, label: p.name })), { testid: 'gs-link-portfolio', label: 'سبد', value: state.portfolioId });
  const aSel = selectEl([], { testid: 'gs-link-asset', label: 'دارایی' });
  const info = h('div', { class: 'gs-modal-info' });
  const ack1 = h('input', { type: 'checkbox', 'data-testid': 'gs-link-ack' });
  const ack2 = needUnit(d) ? h('input', { type: 'checkbox', 'data-testid': 'gs-link-ack-unit' }) : null;
  const err = h('div');
  const confirm = h('button', { class: 'btn primary', type: 'button', disabled: true, 'data-testid': 'gs-link-confirm' }, icon('link', 15), 'تأیید و اتصال');
  let assets = [];
  const cur = () => assets.find((a) => String(a.id) === aSel.value);
  const sync = () => {
    const a = cur();
    const problems = [];
    if (a && d.currency && a.price_currency !== d.currency && !(['IRT', 'IRR'].includes(a.price_currency) && ['IRT', 'IRR'].includes(d.currency))) problems.push(`واحد نماد (${d.currency}) با واحد قیمت دارایی (${a.price_currency}) سازگار نیست.`);
    clear(info).append(...problems.map((p) => notice(p, 'bad')));
    confirm.disabled = !a || a.linked || problems.length > 0 || !ack1.checked || (ack2 && !ack2.checked);
  };
  const loadAssets = async () => {
    clear(aSel).append(h('option', { value: '' }, 'در حال بارگذاری…'));
    const res = await api.get('/api/assets', { portfolio_id: pSel.value, status: 'live', page_size: 500 }, { silent: true }).catch((e) => { clear(err).append(notice(fmtErr(e), 'bad')); return { assets: [] }; });
    assets = res.assets.filter((a) => a.in_portfolio && !a.is_archived).map((a) => ({ ...a, linked: (a.sources || []).some((s) => s.provider_kind === 'iranmarket') }));
    clear(aSel);
    if (!assets.length) aSel.append(h('option', { value: '' }, 'دارایی‌ای در این سبد نیست'));
    assets.forEach((a) => aSel.append(h('option', { value: a.id, disabled: a.linked || null }, `${a.name} (${a.price_currency})${a.linked ? ' — متصل به نماد دیگر' : ''}`)));
    const first = assets.find((a) => !a.linked);
    if (first) aSel.value = String(first.id);
    sync();
  };
  pSel.addEventListener('change', loadAssets); aSel.addEventListener('change', sync); ack1.addEventListener('change', sync); ack2?.addEventListener('change', sync);
  const m = suspendFor({ title: `اتصال ${d.symbol} به دارایی موجود`, wide: false, restoreFocus: ui.panel.querySelector('[data-testid="gs-action-link"]'),
    body: [h('p', { class: 'muted', style: { marginTop: 0 } }, 'ابتدا سبد و سپس دارایی را انتخاب کنید. اتصال فقط منبع قیمت دارایی را تنظیم می‌کند؛ هیچ تراکنش یا موجودی‌ای ساخته نمی‌شود و بدون تأیید شما انجام نمی‌شود.'),
      previewCard(it, d), fieldRow('سبد', pSel), fieldRow('دارایی', aSel), info,
      h('label', { class: 'check gs-check' }, ack1, h('span', null, `تأیید می‌کنم «${nameOf(d.name_fa ? d : it)}» (${d.symbol}) همان دارایی انتخاب‌شدهٔ من است.`)),
      ack2 ? h('label', { class: 'check gs-check' }, ack2, h('span', null, `قیمت این نماد «هر ${unitName(d.unit)}» است؛ مقدار دارایی در تراکنش‌ها با همین واحد ثبت می‌شود.`)) : null, err],
    footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), confirm] });
  confirm.onclick = async () => {
    const a = cur(); if (!a) return;
    confirm.disabled = true; clear(err);
    try {
      await api.post('/api/search/link', { symbol: d.symbol, asset_id: a.id, confirm: true, ack_unit: ack2 ? ack2.checked : false }, { silent: true });
      toast(`«${a.name}» به نماد ${d.symbol} متصل شد.`, 'success');
      m.close(); refreshPage(); if (st.open) openDetail(it);
    } catch (e) { clear(err).append(notice(fmtErr(e), 'bad')); sync(); }
  };
  loadAssets();
}

function createModal(it, d, forPortfolio) {
  const plats = state.meta.platforms.filter((p) => !p.is_archived && p.is_active !== false);
  const portfolios = state.meta.portfolios.filter((p) => !p.is_archived);
  const types = state.meta.asset_types.filter((t) => t.is_active);
  const defType = types.find((t) => t.key === (TYPE_BY_GROUP[it.group] || 'other'))?.key || 'other';
  const name = h('input', { type: 'text', value: nameOf(d.name_fa ? d : it), maxlength: 120, 'data-testid': 'gs-create-name', 'aria-label': 'نام دارایی' });
  const plat = selectEl(plats.map((p) => ({ value: p.id, label: p.name })), { testid: 'gs-create-platform', label: 'پلتفرم' });
  const pf = selectEl(portfolios.map((p) => ({ value: p.id, label: p.name })), { testid: 'gs-create-portfolio', label: 'سبد', value: state.portfolioId });
  const typ = selectEl(types.map((t) => ({ value: t.key, label: t.label })), { testid: 'gs-create-type', label: 'نوع دارایی', value: defType });
  const ack1 = h('input', { type: 'checkbox', 'data-testid': 'gs-create-ack' });
  const ack2 = needUnit(d) ? h('input', { type: 'checkbox', 'data-testid': 'gs-create-ack-unit' }) : null;
  const err = h('div');
  const confirm = h('button', { class: 'btn primary', type: 'button', disabled: true, 'data-testid': 'gs-create-confirm' }, icon('plus', 15), forPortfolio ? 'تأیید و افزودن به سبد' : 'تأیید و ایجاد دارایی');
  const sync = () => { confirm.disabled = !name.value.trim() || !ack1.checked || (ack2 && !ack2.checked) || !plat.value; };
  [name, ack1, ack2].forEach((el) => el?.addEventListener(el === name ? 'input' : 'change', sync));
  const m = suspendFor({ title: forPortfolio ? `افزودن ${d.symbol} به یک سبد` : `ایجاد دارایی جدید از ${d.symbol}`, restoreFocus: ui.panel.querySelector('[data-testid="gs-action-create"]'),
    body: [notice('فقط «تعریف دارایی» انجام می‌شود: دارایی با وزن هدف صفر و منبع قیمت متصل به این نماد ساخته می‌شود. هیچ تراکنش خرید، موجودی یا سفارشی ثبت نمی‌شود.', 'info'),
      previewCard(it, d), fieldRow('نام دارایی', name), h('div', { class: 'form-grid' }, fieldRow('پلتفرم', plat), fieldRow('سبد', pf), fieldRow('نوع دارایی', typ)),
      h('label', { class: 'check gs-check' }, ack1, h('span', null, `تأیید می‌کنم یک دارایی جدید با اتصال به نماد ${d.symbol} ساخته و به سبد انتخاب‌شده اضافه شود.`)),
      ack2 ? h('label', { class: 'check gs-check' }, ack2, h('span', null, `قیمت این نماد «هر ${unitName(d.unit)}» است؛ مقدار دارایی با همین واحد ثبت می‌شود.`)) : null, err],
    footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), confirm] });
  confirm.onclick = async () => {
    confirm.disabled = true; clear(err);
    try {
      const r = await api.post('/api/search/create-asset', { symbol: d.symbol, platform_id: Number(plat.value), portfolio_id: Number(pf.value), name: name.value.trim(), asset_type: typ.value, confirm: true, ack_unit: ack2 ? ack2.checked : false }, { silent: true });
      toast(`دارایی «${r.asset}» ساخته شد (بدون تراکنش و موجودی).`, 'success');
      m.close(); refreshPage(); if (st.open) openDetail(it);
    } catch (e) { clear(err).append(notice(fmtErr(e), 'bad')); sync(); }
  };
  sync();
}

async function portfolioModal(asset, memberOf = []) {
  const portfolios = state.meta.portfolios.filter((p) => !p.is_archived);
  const member = new Set(memberOf.map((p) => p.id));
  // عضویت فعلی از جزئیات سبدها خوانده می‌شود (برای نتایج نماد که فهرست سبدها را ندارند)
  await Promise.all(portfolios.map(async (p) => { if (member.has(p.id)) return; const d = await api.get(`/api/portfolios/${p.id}`, undefined, { silent: true }).catch(() => null); if (d && (d.members || []).some((x) => x.asset_id === asset.id)) member.add(p.id); }));
  const pf = selectEl(portfolios.map((p) => ({ value: p.id, label: `${p.name}${member.has(p.id) ? ' — عضو است' : ''}`, disabled: member.has(p.id) })), { testid: 'gs-pf-select', label: 'سبد' });
  const free = portfolios.find((p) => !member.has(p.id));
  if (free) pf.value = String(free.id);
  const ack = h('input', { type: 'checkbox', 'data-testid': 'gs-pf-ack' });
  const err = h('div');
  const confirm = h('button', { class: 'btn primary', type: 'button', disabled: true, 'data-testid': 'gs-pf-confirm' }, icon('plus', 15), 'تأیید و افزودن');
  const sync = () => { confirm.disabled = !free || !ack.checked || member.has(Number(pf.value)); };
  ack.addEventListener('change', sync); pf.addEventListener('change', sync);
  const m = suspendFor({ title: `افزودن «${asset.name}» به سبد`, restoreFocus: ui.panel.querySelector('[data-testid="gs-action-portfolio"]'),
    body: [h('p', { class: 'muted', style: { marginTop: 0 } }, 'دارایی با وزن هدف صفر به سبد اضافه می‌شود؛ هیچ تراکنش یا موجودی‌ای ثبت نمی‌شود و وزن هدف را بعداً در «سبدها و استراتژی‌ها» تنظیم می‌کنید.'),
      free ? fieldRow('سبد', pf) : notice('این دارایی در همهٔ سبدهای فعال عضو است.', 'info'),
      free ? h('label', { class: 'check gs-check' }, ack, h('span', null, `تأیید می‌کنم «${asset.name}» به سبد انتخاب‌شده اضافه شود.`)) : null, err],
    footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), confirm] });
  confirm.onclick = async () => {
    confirm.disabled = true; clear(err);
    try {
      const r = await api.post('/api/search/add-to-portfolio', { asset_id: asset.id, portfolio_id: Number(pf.value), confirm: true }, { silent: true });
      toast(`«${r.asset}» به سبد «${r.portfolio}» اضافه شد.`, 'success');
      m.close(); refreshPage(); if (st.open && st.detail) openDetail(st.detail);
    } catch (e) { clear(err).append(notice(fmtErr(e), 'bad')); sync(); }
  };
  sync();
}
