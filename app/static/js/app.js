// نقطه ورود رابط کاربری: مسیریابی، منو و بارگذاری صفحات
import { refreshMeta, setPortfolio, state } from './state.js';
import { clear, closeAllModals, h, icon, installDigitFix, loadingBox, notice } from './ui.js';
import { destroyAll, setupCharts } from './charts.js';
import { fmtDate, todayISO } from './format.js';
import { initGlobalSearch } from './globalsearch.js';

const ROUTES = [
  { path: 'dashboard', title: 'داشبورد', icon: 'dashboard', load: () => import('./pages/dashboard.js') },
  { path: 'portfolio', title: 'سبد سرمایه‌گذاری', icon: 'portfolio', load: () => import('./pages/portfolio.js') },
  { path: 'assets', title: 'دارایی‌ها', icon: 'assets', load: () => import('./pages/assets.js') },
  { path: 'platforms', title: 'پلتفرم‌ها', icon: 'platform', load: () => import('./pages/platforms.js') },
  { path: 'portfolios', title: 'سبدها و استراتژی‌ها', icon: 'folder', load: () => import('./pages/portfolios.js') },
  { path: 'transactions', title: 'تراکنش‌ها', icon: 'tx', load: () => import('./pages/transactions.js') },
  { path: 'contributions', title: 'واریزی‌های ماهانه', icon: 'calendar', load: () => import('./pages/contributions.js') },
  { path: 'rebalance', title: 'پیشنهاد خرید', icon: 'target', load: () => import('./pages/rebalance.js') },
  { path: 'risk', title: 'مدیریت ریسک', icon: 'shield', load: () => import('./pages/risk.js') },
  { path: 'reports', title: 'گزارش‌ها', icon: 'report', load: () => import('./pages/reports.js') },
  { path: 'sources', title: 'منابع قیمت', icon: 'sources', load: () => import('./pages/sources.js') },
  { path: 'iran-market', title: 'بازار جامع ایران', icon: 'globe', load: () => import('./pages/iranmarket.js') },
  { path: 'intelligence', title: 'مرکز هوشمندی قیمت‌ها', icon: 'pulse', load: () => import('./pages/intelligence.js') },
  { path: 'prices', title: 'قیمت‌ها و نرخ ارز', icon: 'price', load: () => import('./pages/prices.js') },
  { path: 'settings', title: 'تنظیمات', icon: 'settings', load: () => import('./pages/settings.js') },
];

const view = document.getElementById('view');
const sidebar = document.getElementById('sidebar');
const scrim = document.getElementById('scrim');
let seq = 0;

function buildNav() {
  const nav = document.getElementById('nav');
  clear(nav);
  ROUTES.forEach((r) => nav.append(h('a', { href: `#/${r.path}`, 'data-path': r.path, onclick: () => setMenu(false) }, icon(r.icon, 19), h('span', null, r.title))));
}
function setMenu(open) {
  sidebar.classList.toggle('open', open);
  scrim.classList.toggle('show', open);
  document.getElementById('menu-btn').setAttribute('aria-expanded', String(open));
}

export async function navigate() {
  const hash = location.hash.replace(/^#\/?/, '') || 'dashboard';
  const [path, ...rest] = hash.split('/');
  const route = ROUTES.find((r) => r.path === path) || ROUTES[0];
  const my = ++seq;
  setMenu(false);
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.path === route.path));
  document.getElementById('top-title').textContent = route.title;
  document.title = `${route.title} | CapitalPilot`;
  destroyAll();
  closeAllModals();
  clear(view).append(loadingBox());
  try {
    const mod = await route.load();
    if (my !== seq) return;
    const container = h('div');
    await mod.render(container, rest);
    if (my !== seq) return;
    clear(view).append(container);
    window.scrollTo({ top: 0 });
  } catch (e) {
    if (my !== seq) return;
    console.error(e);
    clear(view).append(notice(`بارگذاری صفحه ناموفق بود: ${e.message || e}`, 'bad'), h('button', { class: 'btn', onclick: () => navigate() }, icon('refresh'), 'تلاش دوباره'));
  }
}
export const reload = () => navigate();
// بارگذاری دوبارهٔ meta (پلتفرم‌ها، انواع، سبدها) و سپس صفحه؛ پس از تغییر ساختار مدیریت صدا زده می‌شود.
export async function reloadAll() { await refreshMeta(); buildSwitcher(); return navigate(); }

function buildSwitcher() {
  const sel = document.getElementById('pf-switch');
  clear(sel);
  state.meta.portfolios.filter((p) => !p.is_archived).forEach((p) => sel.append(h('option', { value: p.id }, p.name)));
  sel.value = String(state.portfolioId);
  document.getElementById('pf-wrap').hidden = sel.options.length < 2;
}

async function boot() {
  installDigitFix();
  setupCharts();
  document.getElementById('menu-btn').append(icon('menu', 22));
  document.getElementById('menu-btn').addEventListener('click', () => setMenu(!sidebar.classList.contains('open')));
  scrim.addEventListener('click', () => setMenu(false));
  buildNav();
  initGlobalSearch();
  try {
    await refreshMeta();
    buildSwitcher();
    document.getElementById('pf-switch').addEventListener('change', (e) => { setPortfolio(Number(e.target.value)); navigate(); });
    document.getElementById('top-meta').textContent = fmtDate(todayISO());
    document.getElementById('side-date').textContent = `امروز: ${fmtDate(todayISO())}`;
  } catch (e) {
    clear(view).append(notice('اتصال به سرور برقرار نشد. برنامه را اجرا کنید و صفحه را دوباره بارگذاری کنید.', 'bad'));
    return;
  }
  window.addEventListener('hashchange', navigate);
  navigate();
}
boot();
