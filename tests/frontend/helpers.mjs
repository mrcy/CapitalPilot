// ابزارهای تست سرتاسری: پیدا کردن مرورگر، فراخوانی API، کلیک بر اساس متن و اسکن ارقام لاتین
import { execFileSync } from 'node:child_process';

export const BASE = process.env.BASE_URL || '';

export async function findBrowser() {
  let puppeteer;
  try { puppeteer = (await import('puppeteer-core')).default; } catch { return { reason: 'puppeteer-core نصب نیست (npm install در tests/frontend)' }; }
  const candidates = [process.env.CHROME_PATH, ...['chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable'].map((n) => {
    try { return execFileSync('which', [n], { encoding: 'utf8' }).trim(); } catch { return null; }
  })].filter(Boolean);
  const args = ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'];
  for (const executablePath of candidates) {
    try { return { browser: await puppeteer.launch({ executablePath, args, headless: 'shell' }) }; } catch { /* بعدی */ }
  }
  try {
    const chromium = (await import('@sparticuz/chromium')).default;
    return { browser: await puppeteer.launch({ args: [...chromium.args, '--no-sandbox'], executablePath: await chromium.executablePath(), headless: 'shell' }) };
  } catch (e) { return { reason: `مرورگر Chrome/Chromium پیدا یا اجرا نشد (${String(e.message).split('\n')[0]})` }; }
}

export async function api(method, path, body) {
  const res = await fetch(BASE + path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)) });
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}: ${text.slice(0, 200)}`);
  return data;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** گوش دادن به خطاهای صفحه؛ آرایهٔ زنده برمی‌گرداند */
export function trackErrors(page, ignore = []) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') { const t = m.text(); if (!ignore.some((i) => t.includes(i))) errors.push(`console: ${t}`); } });
  page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()}`));
  return errors;
}

export async function go(page, route) {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((r) => { location.hash = `#/${r}`; }, route);
  await settle(page);
}

/** صبر تا پایان بارگذاری صفحه (نبودن اسپینر) */
export async function settle(page, timeout = 15000) {
  await sleep(120);
  await page.waitForFunction(() => document.querySelector('#view') && !document.querySelector('#view .loading') && document.querySelector('#view').children.length > 0, { timeout });
  await sleep(250);
}

export async function clickText(page, selector, text, { within = 'body', exact = false } = {}) {
  const handle = await page.evaluateHandle((sel, txt, scope, ex) => {
    const root = document.querySelector(scope) || document;
    return [...root.querySelectorAll(sel)].find((e) => { const t = e.textContent.replace(/\s+/g, ' ').trim(); return ex ? t === txt : t.includes(txt); }) || null;
  }, selector, text, within, exact);
  const el = handle.asElement();
  if (!el) throw new Error(`عنصر «${text}» (${selector}) پیدا نشد`);
  await el.evaluate((e) => e.scrollIntoView({ block: 'center' }));
  await el.click();
  return el;
}
export const clickLabel = async (page, label) => { const el = await page.$(`[aria-label="${label}"]`); if (!el) throw new Error(`دکمهٔ ${label} پیدا نشد`); await el.evaluate((e) => e.scrollIntoView({ block: 'center' })); await el.click(); };

export async function modalOpen(page) { await page.waitForSelector('.modal', { timeout: 8000 }); await sleep(350); }
export async function modalClosed(page) { await page.waitForFunction(() => !document.querySelector('.modal'), { timeout: 8000 }); await sleep(200); }
export async function fill(page, name, value, scope = '.modal') {
  const el = await page.$(`${scope} [name="${name}"]`);
  if (!el) throw new Error(`فیلد ${name} پیدا نشد`);
  await el.focus();
  await el.evaluate((e) => { if (e.select) e.select(); });
  await page.keyboard.press('Backspace');
  if (value !== '') await el.type(String(value), { delay: 5 });
}
export async function submitModal(page) { const el = await page.$('.modal button.primary'); if (!el) throw new Error('دکمهٔ ثبت مودال پیدا نشد'); await el.evaluate((e) => e.scrollIntoView({ block: 'center' })); await el.click(); }
export const choose = (page, name, value, scope = '.modal') => page.select(`${scope} [name="${name}"]`, String(value));

/** ارقام لاتین در متن‌های نمایشی (به‌جز محتوای عمداً LTR مثل نشانی/کلید/کد) */
export function latinDigitScan(page) {
  return page.evaluate(() => {
    const KEEP = 'script,style,textarea,input,code,pre,.kbd,[dir=ltr],.ltr-text,.ltr-input,[data-keep-digits]';
    const out = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (/[0-9]/.test(n.nodeValue) && !(n.parentElement && n.parentElement.closest(KEEP))) out.push(n.nodeValue.trim().slice(0, 80));
    }
    return out;
  });
}
export const overflowOf = (page) => page.evaluate(() => ({
  doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  tables: [...document.querySelectorAll('.table-wrap')].filter((t) => t.offsetParent).map((t) => t.scrollWidth - t.clientWidth),
}));

/** داده‌های نمونهٔ پایه روی دیتابیس موقت تست (قیمت‌ها دستی و فقط برای تست‌اند) */
export async function seedData() {
  const meta = await api('GET', '/api/meta');
  const today = meta.today;
  const plats = Object.fromEntries((await api('GET', '/api/platforms')).map((p) => [p.name, p.id]));
  const assets = (await api('GET', '/api/assets')).assets;
  const d = (n) => { const x = new Date(`${today}T00:00:00Z`); x.setUTCDate(x.getUTCDate() - n); return x.toISOString().slice(0, 10); };
  await api('POST', '/api/transactions', { tx_date: d(40), tx_type: 'deposit', platform_id: plats['مفید'], amount: '300000000' });
  await api('POST', '/api/transactions', { tx_date: d(40), tx_type: 'deposit', platform_id: plats['بیت‌پین'], amount: '200000000' });
  for (const a of assets) {
    const px = a.platform === 'مفید' ? '5000' : '1000000';
    await api('POST', '/api/transactions', { tx_date: d(20), tx_type: 'buy', asset_id: a.id, quantity: '100', unit_price: px });
    await api('POST', '/api/prices', { asset_id: a.id, price: a.platform === 'مفید' ? '5200' : '1100000', recorded_at: `${today}T00:01:00`, source: 'ثبت دستی (تست)', is_approved: true });
  }
  return { today, plats, assets };
}
