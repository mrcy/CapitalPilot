// تست سرتاسری رابط کاربری با Puppeteer روی سرور واقعی با دیتابیس موقت.
// فقط از طریق tests/test_frontend.py (یا با E2E_ALLOW_DESTRUCTIVE=1) اجرا می‌شود چون داده‌ها را پاک می‌کند.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BASE, api, choose, clickLabel, clickText, fill, findBrowser, go, latinDigitScan, modalClosed, modalOpen, overflowOf, seedData, settle, sleep, submitModal, trackErrors } from './helpers.mjs';

const enabled = BASE && process.env.E2E_ALLOW_DESTRUCTIVE === '1';
let browser = null, skipReason = !enabled ? 'BASE_URL و E2E_ALLOW_DESTRUCTIVE=1 تنظیم نشده (این تست داده‌ها را پاک می‌کند)' : '';
let seed = null;
let ROUTES = [];

before(async () => {
  if (skipReason) return;
  const r = await findBrowser();
  if (!r.browser) { skipReason = r.reason; return; }
  browser = r.browser;
  seed = await seedData();
});
after(async () => { if (browser) await browser.close(); });

const e2e = (name, fn) => test(name, { timeout: 120000 }, async (t) => {
  if (skipReason) { t.skip(skipReason); return; }
  const page = await browser.newPage();
  const errors = trackErrors(page);
  try { await fn(page, errors, t); } finally { await page.close(); }
});

async function routes(page) {
  if (!ROUTES.length) { await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' }); await page.waitForSelector('#nav a'); ROUTES = await page.$$eval('#nav a', (a) => a.map((x) => x.dataset.path)); }
  return ROUTES;
}

// ------------------------------------------------------------------ مسیرها
e2e('همهٔ مسیرها در دسکتاپ بدون خطا، بدون رقم لاتین و بدون پیام شکست بارگذاری می‌شوند', async (page, errors) => {
  await page.setViewport({ width: 1366, height: 900 });
  const all = await routes(page);
  assert.ok(all.length >= 14 && all.includes('intelligence'), `مسیرها: ${all}`);
  for (const r of all) {
    await go(page, r);
    assert.equal(await page.$('#view .notice.bad'), null, `پیام خطا در ${r}`);
    const latin = await latinDigitScan(page);
    assert.deepEqual(latin, [], `رقم لاتین در ${r}`);
    assert.ok((await page.$eval('#top-title', (e) => e.textContent)).length > 2, r);
  }
  for (const sub of ['intelligence/assets', 'intelligence/alerts', 'intelligence/performance', 'intelligence/logs']) {
    await go(page, sub);
    assert.equal(await page.$('#view .notice.bad'), null, sub);
    assert.deepEqual(await latinDigitScan(page), [], `رقم لاتین در ${sub}`);
  }
  assert.deepEqual(errors, []);
});

e2e('موبایل: منوی همبرگری باز و بسته می‌شود و همهٔ مسیرها از منو قابل رفتن‌اند و اسکرول افقی صفحه ندارند', async (page, errors) => {
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  const all = await routes(page);
  await go(page, 'dashboard');
  assert.equal(await page.$eval('#sidebar', (e) => e.classList.contains('open')), false);
  for (const r of all) {
    await page.click('#menu-btn');
    await page.waitForFunction(() => document.querySelector('#sidebar').classList.contains('open'));
    await sleep(450);
    assert.equal(await page.$eval('#menu-btn', (e) => e.getAttribute('aria-expanded')), 'true');
    await page.$eval(`#nav a[data-path="${r}"]`, (e) => { e.scrollIntoView({ block: 'center' }); e.click(); });
    await page.waitForFunction((p) => location.hash.startsWith(`#/${p}`), {}, r);
    await settle(page);
    assert.equal(await page.$eval('#sidebar', (e) => e.classList.contains('open')), false, `منو پس از رفتن به ${r} بسته نشد`);
    assert.equal(await page.$eval('#nav a.active', (e) => e.dataset.path), r);
    const ov = await overflowOf(page);
    assert.ok(ov.doc <= 1, `اسکرول افقی صفحه در ${r}: ${ov.doc}`);
  }
  // بستن با کلیک روی پرده
  await page.click('#menu-btn');
  await page.waitForFunction(() => document.querySelector('#sidebar').classList.contains('open'));
  await page.mouse.click(20, 400);
  await page.waitForFunction(() => !document.querySelector('#sidebar').classList.contains('open'));
  assert.deepEqual(errors, []);
});

e2e('جدول پیشنهاد خرید در عرض ۱۲۰۰ پیکسل اسکرول افقی ندارد', async (page) => {
  for (const width of [1200, 1280, 1440]) {
    await page.setViewport({ width, height: 900 });
    await go(page, 'rebalance');
    assert.ok(await page.$('#view table.data'), 'جدول پیشنهاد خرید باید نمایش داده شود (داده‌های پایه)');
    const ov = await overflowOf(page);
    assert.ok(ov.doc <= 0, `سرریز صفحه در ${width}`);
    assert.ok(ov.tables.every((x) => x <= 1), `اسکرول افقی جدول در ${width}: ${ov.tables}`);
  }
});

// ------------------------------------------------------------------ فرم‌ها
e2e('پلتفرم: افزودن، ویرایش، بایگانی، بازیابی و حذف', async (page) => {
  await page.setViewport({ width: 1366, height: 900 });
  await go(page, 'platforms');
  await clickText(page, 'button', 'پلتفرم جدید');
  await modalOpen(page);
  await fill(page, 'name', 'پلتفرم آزمون');
  await submitModal(page);
  await modalClosed(page);
  const find = async () => (await api('GET', '/api/platforms')).find((p) => p.name.startsWith('پلتفرم آزمون'));
  let p = await find();
  assert.ok(p, 'پلتفرم ساخته نشد');
  await settle(page);
  await clickLabel(page, 'ویرایش پلتفرم آزمون');
  await modalOpen(page);
  await fill(page, 'name', 'پلتفرم آزمون ۲');
  await submitModal(page);
  await modalClosed(page);
  assert.equal((await find()).name, 'پلتفرم آزمون ۲');
  await settle(page);
  await clickLabel(page, 'بایگانی پلتفرم آزمون ۲');
  await modalOpen(page);
  await clickText(page, '.modal .btn', 'بایگانی');
  await modalClosed(page);
  await sleep(500);
  assert.equal((await find()).is_archived, true);
  // دیدن بایگانی‌ها و بازیابی
  await settle(page);
  await page.select('select[aria-label="وضعیت"]', 'archived');
  await sleep(600);
  await clickLabel(page, 'بازیابی پلتفرم آزمون ۲');
  await sleep(700);
  assert.equal((await find()).is_archived, false);
  // حذف (بدون دارایی/تراکنش)
  await settle(page);
  await page.select('select[aria-label="وضعیت"]', 'live').catch(() => {});
  await sleep(500);
  await clickLabel(page, 'حذف پلتفرم آزمون ۲');
  await modalOpen(page);
  await clickText(page, '.modal .btn', 'حذف');
  await modalClosed(page);
  await sleep(500);
  assert.equal(await find(), undefined);
});

e2e('تراکنش: افزودن با ورودی لاتین (قالب‌بندی هزارگان) سپس ویرایش و حذف', async (page) => {
  await page.setViewport({ width: 1366, height: 900 });
  const before = (await api('GET', '/api/transactions?limit=500')).total;
  await go(page, 'transactions');
  await clickText(page, 'button', 'تراکنش جدید');
  await modalOpen(page);
  await choose(page, 'tx_type', 'deposit');
  await sleep(200);
  await choose(page, 'platform_id', seed.plats['مفید']);
  await fill(page, 'amount', '1234567');
  await page.$eval('.modal [name="amount"]', (e) => e.blur());
  const shown = await page.$eval('.modal [name="amount"]', (e) => e.value);
  assert.equal(shown, '۱٬۲۳۴٬۵۶۷', 'فیلد مبلغ باید هنگام ترک فیلد با ارقام فارسی و هزارگان نمایش داده شود');
  await submitModal(page);
  await modalClosed(page);
  let res = await api('GET', '/api/transactions?limit=500');
  assert.equal(res.total, before + 1);
  const created = res.items.find((t) => t.tx_type === 'deposit' && Number(t.total_amount) === 1234567);
  assert.ok(created, 'مبلغ ذخیره‌شده باید ۱۲۳۴۵۶۷ باشد');
  await settle(page);
  await page.click('button[aria-label="ویرایش تراکنش"]');
  await modalOpen(page);
  await fill(page, 'amount', '۷۶۵٬۴۳۲');
  await submitModal(page);
  await modalClosed(page);
  res = await api('GET', '/api/transactions?limit=500');
  assert.ok(res.items.find((t) => t.id === created.id && Number(t.total_amount) === 765432), 'ویرایش اعمال نشد');
  await settle(page);
  // اعتبارسنجی: مبلغ خالی
  await clickText(page, 'button', 'تراکنش جدید');
  await modalOpen(page);
  await choose(page, 'tx_type', 'deposit');
  await submitModal(page);
  await page.waitForSelector('.modal .form-error:not([hidden])');
  await clickText(page, '.modal button', 'انصراف');
  await modalClosed(page);
  await settle(page);
  await page.click('button[aria-label="حذف تراکنش"]');
  await modalOpen(page);
  await clickText(page, '.modal .btn', 'حذف');
  await modalClosed(page);
  await sleep(500);
  assert.equal((await api('GET', '/api/transactions?limit=500')).total, before);
});

e2e('قیمت دستی: ثبت و حذف از صفحهٔ قیمت‌ها', async (page) => {
  await page.setViewport({ width: 1366, height: 900 });
  const target = seed.assets[0];
  const count = async () => (await api('GET', `/api/prices?asset_id=${target.id}`)).length;
  const before = await count();
  await go(page, 'prices');
  await clickText(page, 'button', 'ثبت قیمت', { exact: true });
  await modalOpen(page);
  await choose(page, 'asset_id', target.id);
  await fill(page, 'price', '5300');
  await submitModal(page);
  await modalClosed(page);
  assert.equal(await count(), before + 1);
  const newest = (await api('GET', `/api/prices?asset_id=${target.id}`))[0];
  assert.equal(newest.origin, 'manual');
  await settle(page);
  assert.ok(await page.$('#view .badge'), 'نشان منشأ باید دیده شود');
  await page.click('button[aria-label="حذف قیمت"]');
  await modalOpen(page);
  await clickText(page, '.modal .btn', 'حذف');
  await modalClosed(page);
  await sleep(500);
  assert.equal(await count(), before);
});

e2e('دارایی: افزودن، بایگانی، بازیابی و ویرایش', async (page) => {
  await page.setViewport({ width: 1366, height: 900 });
  const find = async () => (await api('GET', '/api/assets?status=all')).assets.find((a) => a.name === 'دارایی آزمون');
  await go(page, 'assets');
  await clickText(page, 'button', 'دارایی جدید');
  await modalOpen(page);
  await fill(page, 'name', 'دارایی آزمون');
  await fill(page, 'symbol', 'آزمون');
  await submitModal(page);
  await modalClosed(page);
  let a = await find();
  assert.ok(a && a.is_archived === false, 'دارایی ساخته نشد');
  await settle(page);
  await clickLabel(page, 'بایگانی دارایی آزمون');
  await modalOpen(page).catch(() => {});
  if (await page.$('.modal')) { await clickText(page, '.modal .btn', 'بایگانی'); await modalClosed(page); }
  await sleep(600);
  assert.equal((await find()).is_archived, true);
  await settle(page);
  await page.select('select[aria-label="وضعیت"]', 'archived');
  await sleep(600);
  await clickLabel(page, 'بازیابی دارایی آزمون');
  await sleep(700);
  assert.equal((await find()).is_archived, false);
  // ویرایش
  await settle(page);
  await page.select('select[aria-label="وضعیت"]', 'live').catch(() => {});
  await sleep(500);
  await clickLabel(page, 'ویرایش دارایی آزمون');
  await modalOpen(page);
  await fill(page, 'symbol', 'آزمون۲');
  await submitModal(page);
  await modalClosed(page);
  assert.equal((await find()).symbol, 'آزمون۲');
});

// ------------------------------------------------------------------ بازار جامع ایران (Iran Market Data)
// دیتابیس این آزمون با همان مسیر واقعی دریافت و پردازش (فایل واقعی ذخیره‌شده، بدون شبکه) پر شده است.
const rowsOf = (page) => page.$$eval('[data-testid="im-table"] tbody tr', (r) => r.length);
const waitRows = (page, pred) => page.waitForFunction((src) => { const n = document.querySelectorAll('[data-testid="im-table"] tbody tr').length; return new Function('n', `return ${src}`)(n); }, { timeout: 10000 }, pred);

e2e('بازار جامع ایران (دسکتاپ): شاخص‌ها، دسته‌های پویا، جست‌وجو، فیلتر، مرتب‌سازی، صفحه‌بندی و جزئیات', async (page, errors) => {
  await page.setViewport({ width: 1366, height: 900 });
  const ov = await api('GET', '/api/iran-market/overview');
  assert.equal(ov.totals.total, 1042);
  await go(page, 'iran-market');
  assert.equal(await page.$('#view .notice.bad'), null);
  assert.equal((await page.$$('[data-testid="im-kpis"] .kpi')).length, 7);
  assert.equal((await page.$$('.im-cats .tab')).length, ov.categories.length + 1); // دسته‌ها از دادهٔ فایل
  assert.equal(await rowsOf(page), 50);
  assert.deepEqual(await latinDigitScan(page), []);
  // جست‌وجو (نماد لاتین)
  const q = await api('GET', '/api/iran-market/symbols?q=USD_IRR&page_size=200');
  await page.type('.toolbar input[type="search"]', 'USD_IRR');
  await waitRows(page, `n === ${Math.min(q.total, 50)}`);
  assert.ok(q.total >= 1);
  // فیلتر دسته با چیپ
  await page.evaluate(() => { document.querySelector('.toolbar input[type="search"]').value = ''; document.querySelector('.toolbar input[type="search"]').dispatchEvent(new Event('input')); });
  await sleep(700);
  const gold = ov.categories.find((c) => c.key === 'gold');
  await page.click('.im-cats [data-cat="gold"]');
  await waitRows(page, `n === ${Math.min(gold.count, 50)}`);
  // فیلتر وضعیت قدیمی + مرتب‌سازی قیمت
  await page.click('.im-cats [data-cat=""]');
  await page.select('select[aria-label="وضعیت"]', 'stale');
  await sleep(700);
  const st = await api('GET', '/api/iran-market/symbols?status=stale&page_size=1');
  assert.equal(await page.$eval('.pager span', (e) => e.textContent.includes('از')), true);
  assert.ok(st.total > 0);
  await page.select('select[aria-label="وضعیت"]', '');
  await page.select('select[aria-label="مرتب‌سازی"]', 'price:desc');
  await sleep(700);
  // صفحه‌بندی
  await clickText(page, '.pager button', 'بعدی');
  await sleep(700);
  assert.match((await page.$eval('.pager', (e) => e.textContent)).replace(/[\u2066\u2069]/g, ''), /صفحه ۲ از/);
  // جزئیات یک نماد
  await go(page, 'iran-market/s/GOLD_18K_IRR');
  assert.ok(await page.$('[data-testid="im-detail"]'));
  assert.equal(await page.$('#view .notice.bad'), null);
  assert.ok((await page.$eval('#view', (e) => e.textContent)).includes('گرم'));
  assert.deepEqual(await latinDigitScan(page), []);
  // سلامت
  await go(page, 'iran-market/health');
  assert.ok(await page.$('[data-testid="im-health"]'));
  assert.deepEqual(await latinDigitScan(page), []);
  assert.deepEqual(errors, []);
});

e2e('بازار جامع ایران (موبایل ۳۹۰): بدون اسکرول افقی، جدول کارتی و جزئیات', async (page, errors) => {
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  await go(page, 'iran-market');
  assert.equal(await rowsOf(page), 50);
  let o = await overflowOf(page);
  assert.ok(o.doc <= 1, `اسکرول افقی صفحه: ${o.doc}`);
  assert.ok(o.tables.every((x) => x <= 1), `اسکرول افقی جدول: ${o.tables}`);
  await go(page, 'iran-market/s/USD_IRR_FREE');
  o = await overflowOf(page);
  assert.ok(o.doc <= 1, `اسکرول افقی جزئیات: ${o.doc}`);
  await go(page, 'iran-market/health');
  o = await overflowOf(page);
  assert.ok(o.doc <= 1 && o.tables.every((x) => x <= 1), `سلامت: ${JSON.stringify(o)}`);
  await go(page, 'sources');
  assert.ok(await page.$('[data-testid="im-source-health"]'));
  o = await overflowOf(page);
  assert.ok(o.doc <= 1, `منابع قیمت: ${o.doc}`);
  assert.deepEqual(errors, []);
});

e2e('اتصال نماد به دارایی در فرم دارایی: جست‌وجو، پیش‌نمایش، تأیید صریح، تغییر و قطع اتصال', async (page, errors) => {
  await page.setViewport({ width: 1366, height: 900 });
  const imId = (await api('GET', '/api/market-data/providers')).find((p) => p.kind === 'iranmarket').id;
  const find = async () => (await api('GET', '/api/assets?status=all')).assets.find((a) => a.name === 'دلار آزاد آزمون');
  const pick = async (symbol, acks) => {
    await clickText(page, '.modal [data-testid="im-pick"]', '');
    await page.waitForSelector('[data-testid="im-search"]');
    await page.type('[data-testid="im-search"]', symbol);
    await page.waitForFunction((sym) => [...document.querySelectorAll('.im-row')].some((r) => r.textContent.includes(sym)), { timeout: 8000 }, symbol);
    await clickText(page, '.im-row .btn', 'مشاهده و انتخاب');
    await page.waitForSelector('[data-testid="im-preview"]');
    assert.equal(await page.$eval('[data-testid="im-confirm"]', (b) => b.disabled), true, 'بدون تأیید نباید فعال باشد');
    for (const a of acks) await page.click(`[data-testid="${a}"]`);
    assert.equal(await page.$eval('[data-testid="im-confirm"]', (b) => b.disabled), false);
    await page.click('[data-testid="im-confirm"]');
    await sleep(500);
  };
  await go(page, 'assets');
  await clickText(page, 'button', 'دارایی جدید');
  await modalOpen(page);
  await fill(page, 'name', 'دلار آزاد آزمون');
  await fill(page, 'symbol', 'USDT');
  await clickText(page, '.modal button', 'افزودن منبع');
  await page.select('.modal select[aria-label="منبع"]', String(imId));
  assert.ok(await page.$eval('.modal [data-testid="im-pick"]', (b) => !b.closest('[hidden]') && !b.parentElement.hidden));
  // ذخیره بدون انتخاب نماد رد می‌شود
  await submitModal(page);
  await sleep(500);
  assert.ok(await page.$('.modal .form-error:not([hidden])'), 'باید خطای انتخاب نماد نشان داده شود');
  assert.equal(await find(), undefined);
  await pick('USD_IRR_FREE', ['im-ack']);
  await submitModal(page);
  await modalClosed(page);
  let a = await find();
  assert.ok(a, 'دارایی ساخته نشد');
  let src = (await api('GET', `/api/assets/${a.id}`)).sources;
  assert.equal(src.length, 1);
  assert.equal(src[0].external_id, 'USD_IRR_FREE');
  assert.equal(src[0].link.currency, 'IRT');
  assert.ok(src[0].link.confirmed_at);
  // تغییر نماد: نماد دارای واحد گرم نیاز به تأیید واحد هم دارد
  await settle(page);
  await sleep(800);
  await clickLabel(page, 'ویرایش دلار آزاد آزمون');
  await modalOpen(page);
  await pick('GOLD_18K_IRR', ['im-ack', 'im-ack-unit']);
  await submitModal(page);
  await modalClosed(page);
  src = (await api('GET', `/api/assets/${a.id}`)).sources;
  assert.equal(src[0].external_id, 'GOLD_18K_IRR');
  assert.equal(src[0].link.unit, 'gram');
  // قطع اتصال با حذف ردیف منبع (انسداد نمادهای ناسازگار در تست‌های پایتون پوشش داده شده است)
  await settle(page);
  await sleep(800);
  await clickLabel(page, 'ویرایش دلار آزاد آزمون');
  await modalOpen(page);
  await clickLabel(page, 'حذف منبع یا قطع اتصال');
  await submitModal(page);
  await modalClosed(page);
  assert.deepEqual((await api('GET', `/api/assets/${a.id}`)).sources, []);
  // قیمت‌ها و تراکنش‌ها دست‌نخورده‌اند و دارایی‌ای خودکار ساخته نشده است
  assert.equal((await api('GET', '/api/assets?status=all')).assets.filter((x) => x.name === 'دلار آزاد آزمون').length, 1);
  await api('POST', `/api/assets/${a.id}/archive`).catch(() => {});
  assert.deepEqual(errors, []);
});

// ------------------------------------------------------------------ حالت‌های بارگذاری، خطا و خالی
e2e('حالت بارگذاری، خطای سرور با تلاش دوباره و قطع شبکه', async (page) => {
  await page.setViewport({ width: 1366, height: 900 });
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle0' });
  await page.setRequestInterception(true);
  let mode = 'delay';
  page.on('request', async (req) => {
    const u = req.url();
    if (u.includes('/api/dashboard') && mode === 'delay') { await sleep(1500); return req.continue(); }
    if (u.includes('/api/portfolio') && mode === 'fail') return req.respond({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { code: 'server', message: 'خطای آزمایشی سرور' } }) });
    if (u.includes('/api/transactions') && mode === 'offline') return req.abort('failed');
    return req.continue();
  });
  // loading
  await page.evaluate(() => { location.hash = '#/dashboard'; });
  await page.waitForSelector('#view .loading', { timeout: 5000 });
  await settle(page);
  // خطای سرور
  mode = 'fail';
  await page.evaluate(() => { location.hash = '#/portfolio'; });
  await page.waitForSelector('#view .notice.bad', { timeout: 8000 });
  const msg = await page.$eval('#view .notice.bad', (e) => e.textContent);
  assert.ok(msg.includes('بارگذاری صفحه ناموفق بود'), msg);
  mode = 'ok';
  await clickText(page, '#view button', 'تلاش دوباره');
  await settle(page);
  assert.equal(await page.$('#view .notice.bad'), null, 'پس از رفع خطا و تلاش دوباره صفحه باید بارگذاری شود');
  // قطع شبکه
  mode = 'offline';
  await page.evaluate(() => { location.hash = '#/transactions'; });
  await page.waitForSelector('#view .notice.bad', { timeout: 8000 });
  assert.ok((await page.$eval('#view .notice.bad', (e) => e.textContent)).includes('ارتباط با سرور'));
});

// ------------------------------------------------------------------ بازیابی و پاک‌سازی
e2e('بازیابی از فایل پشتیبان و پاک‌سازی کامل (دو مرحله‌ای) و حالت‌های خالی', async (page) => {
  await page.setViewport({ width: 1366, height: 900 });
  const snapshot = async () => ({ tx: (await api('GET', '/api/transactions?limit=500')).total, pf: await api('GET', '/api/portfolio'), assets: (await api('GET', '/api/assets')).assets.length, prices: (await api('GET', '/api/prices')).length });
  const base = await snapshot();
  assert.ok(base.tx >= 7 && base.prices >= 5);
  const backup = await (await fetch(`${BASE}/api/backup/export`)).text();
  const dir = mkdtempSync(join(tmpdir(), 'cp-e2e-'));
  const file = join(dir, 'backup.json');
  writeFileSync(file, backup);

  // پاک‌سازی تراکنش‌ها و قیمت‌ها از رابط
  await go(page, 'settings');
  await clickText(page, 'button', 'پاک‌سازی تراکنش‌ها و قیمت‌ها');
  await modalOpen(page);
  await clickText(page, '.modal .btn', 'ادامه');
  await sleep(500);
  await page.waitForSelector('.modal [name="phrase"]');
  // بدون تیک تأیید رد می‌شود؛ سپس عبارت اشتباه هم رد می‌شود
  await fill(page, 'phrase', 'اشتباه');
  await submitModal(page);
  await page.waitForSelector('.modal .form-error:not([hidden])', { timeout: 5000 });
  assert.equal((await api('GET', '/api/transactions?limit=5')).total, base.tx);
  await page.click('.modal [name="understand"]');
  await submitModal(page);
  await page.waitForSelector('.modal .form-error:not([hidden])', { timeout: 5000 });
  assert.equal((await api('GET', '/api/transactions?limit=5')).total, base.tx, 'با عبارت اشتباه نباید پاک شود');
  const phrase = await page.$eval('.modal .lbl', (e) => (e.textContent.match(/«(.+?)»/) || [])[1]);
  assert.ok(phrase);
  await fill(page, 'phrase', phrase);
  await submitModal(page);
  await modalClosed(page);
  await sleep(600);
  assert.equal((await api('GET', '/api/transactions?limit=5')).total, 0, 'تراکنش‌ها باید پاک شوند');
  assert.equal((await api('GET', '/api/prices')).length, 0);
  assert.equal((await api('GET', '/api/assets')).assets.length, base.assets, 'دارایی‌ها باید حفظ شوند');

  // حالت‌های خالی
  for (const r of ['transactions', 'dashboard', 'portfolio', 'prices', 'intelligence/assets', 'intelligence/logs']) {
    await go(page, r);
    assert.equal(await page.$('#view .notice.bad'), null, `خطا در حالت خالی ${r}`);
  }
  await go(page, 'transactions');
  assert.ok(await page.$('#view .empty-note'), 'پیام حالت خالی تراکنش‌ها');
  await go(page, 'intelligence/assets');
  const statuses = await page.$$eval('#view table tbody tr', (rows) => rows.length);
  assert.ok(statuses > 0);
  assert.equal(await page.$('#view .badge.ok'), null, 'بدون قیمت هیچ دارایی «معتبر» نیست');

  // بازیابی از فایل
  await go(page, 'settings');
  const input = await page.$('input[type=file]');
  await input.uploadFile(file);
  await modalOpen(page);
  await clickText(page, '.modal .btn', 'بازیابی');
  await modalClosed(page);
  await sleep(1200);
  const after = await snapshot();
  assert.equal(after.tx, base.tx);
  assert.equal(after.prices, base.prices);
  assert.deepEqual(after.pf.totals ?? after.pf.summary ?? after.pf, base.pf.totals ?? base.pf.summary ?? base.pf, 'ارزش‌گذاری پس از بازیابی باید با قبل یکسان باشد');

  // فایل نامعتبر
  const bad = join(dir, 'bad.json');
  writeFileSync(bad, '{not json');
  await go(page, 'settings');
  await (await page.$('input[type=file]')).uploadFile(bad);
  await page.waitForSelector('.toast.error, #toasts .error, #toasts div', { timeout: 5000 });
  assert.equal((await snapshot()).tx, base.tx, 'فایل خراب نباید داده‌ها را تغییر دهد');

  // بازنشانی کامل
  await go(page, 'settings');
  await clickText(page, 'button', 'بازنشانی کامل به حالت اولیه');
  await modalOpen(page);
  await clickText(page, '.modal .btn', 'ادامه');
  await page.waitForSelector('.modal [name="phrase"]');
  const phrase2 = await page.$eval('.modal .lbl', (e) => (e.textContent.match(/«(.+?)»/) || [])[1]);
  await page.click('.modal [name="understand"]');
  await fill(page, 'phrase', phrase2);
  await submitModal(page);
  await modalClosed(page);
  await sleep(800);
  const wiped = await snapshot();
  assert.equal(wiped.tx, 0);
  assert.equal(wiped.prices, 0);
  // برنامه پس از بازنشانی هنوز کار می‌کند و دادهٔ پیش‌فرض برگشته است
  await go(page, 'dashboard');
  assert.equal(await page.$('#view .notice.bad'), null);
  assert.ok(wiped.assets >= 1);
});
