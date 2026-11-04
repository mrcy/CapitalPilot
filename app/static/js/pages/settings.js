import { api } from '../api.js';
import { state, refreshMeta } from '../state.js';
import { reload } from '../app.js';
import { badge, buildForm, clear, confirmDialog, downloadBlob, formModal, h, icon, modal, notice, pageHead, table, toast, validateRequired } from '../ui.js';
import { money, num, pct, parseDecimal, faDigits, fmtDateTime } from '../format.js';

export async function render(root) {
  const [s, assetsRes, backups] = await Promise.all([api.get('/api/settings'), api.get('/api/assets', { page_size: 500, portfolio_id: state.meta.settings.portfolio_id }), api.get('/api/backup/list')]);
  const assets = assetsRes.assets;
  root.append(pageHead('تنظیمات', 'تمام اعداد برنامه سرمایه‌گذاری، ترکیب هدف، واحد پول و پشتیبان‌گیری'));
  root.append(notice(`بخش‌های «برنامه» و «ترکیب هدف» این صفحه مربوط به سبد پیش‌فرض («${state.meta.settings.portfolio_name}») است. سرمایه، افق و وزن‌های سایر سبدها را در صفحهٔ «سبدها و استراتژی‌ها» تنظیم کنید.`, 'info'));
  root.append(planSection(s), allocationSection(s, assets), platformsSection(), currenciesSection(), backupSection(backups), dangerSection());
}

const section = (title, ...kids) => h('section', { class: 'card', style: { marginBottom: '16px' } }, h('h2', { style: { fontSize: '16px', marginBottom: '12px' } }, title), ...kids);

function planSection(s) {
  const fields = [
    { name: 'initial_capital', label: 'سرمایه اولیه (تومان)', type: 'decimal', required: true },
    { name: 'monthly_contribution', label: 'واریزی ماهانه (تومان)', type: 'decimal', required: true },
    { name: 'horizon_months', label: 'افق سرمایه‌گذاری (ماه)', type: 'int', required: true, hint: '۱۲ ماه، ۳۶ ماه (۳ سال) یا هر مقدار دلخواه' },
    { name: 'plan_start_date', label: 'تاریخ شروع برنامه', type: 'date', required: true },
    { name: 'max_drawdown_pct', label: 'سقف افت قابل تحمل (٪)', type: 'decimal', required: true, hint: 'آستانه‌های هشدار: ۶۰٪، ۸۰٪ و ۱۰۰٪ این سقف (۱۵، ۲۰، ۲۵٪ برای سقف ۲۵٪).' },
    { name: 'concentration_limit_pct', label: 'سقف تمرکز در یک دارایی (٪)', type: 'decimal', required: true },
    { name: 'deviation_warning_pp', label: 'آستانه هشدار انحراف از وزن هدف (واحد درصد)', type: 'decimal', required: true },
    { name: 'max_price_age_days', label: 'حداکثر سن قیمت معتبر (روز)', type: 'int', required: true },
    { name: 'calendar', label: 'تقویم', type: 'select', options: [{ value: 'jalali', label: 'شمسی (جلالی)' }, { value: 'gregorian', label: 'میلادی' }] },
    { name: 'currency_label', label: 'برچسب واحد پول نمایشی', type: 'text', required: true },
    { name: 'apply_to_past_unpaid', label: 'تغییر مبلغ/تاریخ روی دوره‌های گذشته پرداخت‌نشده هم اعمال شود', type: 'checkbox', wide: true },
  ];
  const f = buildForm(fields, s);
  const err = h('div', { class: 'form-error', hidden: true });
  const btn = h('button', { class: 'btn primary', type: 'button', onclick: save }, 'ذخیره تنظیمات');
  async function save() {
    const v = f.getValues();
    const msg = validateRequired(fields, v);
    if (msg) { err.textContent = msg; err.hidden = false; return; }
    err.hidden = true; btn.disabled = true;
    try {
      await api.put('/api/settings', { ...v, initial_capital: v.initial_capital, monthly_contribution: v.monthly_contribution });
      await refreshMeta(); toast('تنظیمات ذخیره شد. دوره‌های آینده برنامه واریزی به‌روز شد.', 'success'); reload();
    } catch (e) { err.textContent = e.message; err.hidden = false; } finally { btn.disabled = false; }
  }
  return section('برنامه سرمایه‌گذاری و ریسک', h('p', { class: 'muted', style: { marginTop: 0 } }, `برنامه هدف: ${money(s.initial_capital)} سرمایه اولیه + ${num(s.horizon_months)} × ${money(s.monthly_contribution)} = ${money(s.plan_target_total)}. این اعداد فقط «برنامه» هستند و خرید واقعی ثبت نمی‌کنند.`), f.form, err, h('div', { style: { marginTop: '12px' } }, btn));
}

function allocationSection(s, assets) {
  const active = assets.filter((a) => a.is_active);
  const inputs = {};
  const sumEl = h('b', { class: 'sum-badge' });
  const upd = () => {
    const sum = active.reduce((t, a) => t + (Number(parseDecimal(inputs[a.id].value)) || 0), 0);
    sumEl.className = `sum-badge ${Math.abs(sum - 100) < 1e-9 ? 'pos' : 'neg'}`;
    sumEl.textContent = `مجموع: ${num(sum, 2)}٪`;
  };
  const rows = active.map((a) => {
    const inp = h('input', { type: 'text', class: 'ltr-input weights-input', inputmode: 'decimal', value: faDigits(a.target_weight), 'aria-label': `وزن ${a.name}` });
    inp.addEventListener('input', () => { upd(); upd2(); });
    inputs[a.id] = inp;
    return { a, inp };
  });
  const plan = (a, k) => h('span', { class: 'plan-cell', 'data-id': a.id, 'data-k': k });
  let tbl;
  const upd2 = () => {
    rows.forEach(({ a }) => {
      const w = Number(parseDecimal(inputs[a.id].value)) || 0;
      tbl.querySelectorAll(`.plan-cell[data-id="${a.id}"]`).forEach((el) => { el.textContent = money(Number(el.dataset.k === 'i' ? s.initial_capital : s.monthly_contribution) * w / 100, 0, false); });
    });
  };
  tbl = table([
    { label: 'دارایی', render: (r) => r.a.name }, { label: 'پلتفرم', render: (r) => r.a.platform },
    { label: 'وزن هدف (٪)', render: (r) => r.inp },
    { label: 'سهم از سرمایه اولیه', class: 'num', render: (r) => plan(r.a, 'i') }, { label: 'سهم از واریزی ماهانه', class: 'num', render: (r) => plan(r.a, 'm') },
  ], rows);
  const btn = h('button', { class: 'btn primary', onclick: async () => {
    const weights = {};
    for (const a of active) { const v = parseDecimal(inputs[a.id].value); if (v === null || Number.isNaN(v)) { toast(`وزن «${a.name}» نامعتبر است.`, 'error'); return; } weights[a.id] = v; }
    await api.put('/api/assets/target-weights', { weights }); toast('ترکیب هدف ذخیره شد.', 'success'); await refreshMeta(); reload();
  } }, 'ذخیره ترکیب هدف');
  queueMicrotask(() => { upd(); upd2(); });
  return section('ترکیب هدف دارایی‌ها', h('p', { class: 'muted', style: { marginTop: 0 } }, 'درصدها نسبت به کل سبد هستند و مجموع آن‌ها باید دقیقاً ۱۰۰٪ باشد. برای افزودن/غیرفعال کردن دارایی به صفحه «دارایی‌ها» بروید.'), tbl, h('div', { class: 'inline-form', style: { marginTop: '12px', justifyContent: 'space-between' } }, sumEl, btn));
}

function platformsSection() {
  return section('پلتفرم‌ها', h('p', { class: 'muted', style: { marginTop: 0 } }, 'افزودن، ویرایش، غیرفعال‌سازی و بایگانی پلتفرم‌ها در بخش مستقل «پلتفرم‌ها» انجام می‌شود.'),
    h('a', { class: 'btn', href: '#/platforms' }, icon('platform'), 'مدیریت پلتفرم‌ها'));
}

function currenciesSection() {
  const open = (c) => formModal({
    title: c ? `ویرایش ${c.code}` : 'واحد پول جدید', submitLabel: 'ذخیره', values: c || { is_active: true },
    fields: [{ name: 'code', label: 'کد (مثل USD)', type: 'text', required: true }, { name: 'name', label: 'نام', type: 'text', required: true }, { name: 'symbol', label: 'نماد', type: 'text' }, { name: 'is_active', label: 'فعال', type: 'checkbox' }],
    onSubmit: async (x, m) => { const body = { code: x.code, name: x.name, symbol: x.symbol || '', is_active: x.is_active }; if (c) await api.put(`/api/currencies/${c.code}`, body); else await api.post('/api/currencies', body); m.close(); await refreshMeta(); reload(); },
  });
  return section('واحدهای پول', h('p', { class: 'muted', style: { marginTop: 0 } }, 'واحد پایه همیشه تومان است. ارزهای دیگر برای دارایی‌های خارجی و ثبت نرخ تبدیل استفاده می‌شوند.'),
    table([{ label: 'کد', render: (c) => c.code }, { label: 'نام', render: (c) => c.name }, { label: 'وضعیت', render: (c) => (c.is_base ? badge('واحد پایه', 'info') : c.is_active ? badge('فعال', 'ok') : badge('غیرفعال')) },
      { label: '', render: (c) => h('div', { class: 'row-actions' }, h('button', { class: 'icon-btn', onclick: () => open(c) }, icon('edit')),
        c.is_base ? null : h('button', { class: 'icon-btn', onclick: async () => { if (await confirmDialog({ message: `واحد «${c.code}» حذف شود؟`, danger: true, confirmLabel: 'حذف' })) { await api.del(`/api/currencies/${c.code}`); await refreshMeta(); reload(); } } }, icon('trash'))) }], state.meta.currencies),
    h('div', { style: { marginTop: '10px' } }, h('button', { class: 'btn', onclick: () => open(null) }, icon('plus'), 'واحد پول جدید')));
}

function backupSection(backups) {
  const fileInput = h('input', { type: 'file', accept: 'application/json,.json', hidden: true });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (!file) return;
    let text;
    try { text = await file.text(); JSON.parse(text); } catch { toast('فایل انتخاب‌شده JSON معتبر نیست.', 'error'); fileInput.value = ''; return; }
    const ok = await confirmDialog({ title: 'بازیابی از پشتیبان', danger: true, confirmLabel: 'بازیابی', message: 'با بازیابی، تمام اطلاعات فعلی با محتوای فایل پشتیبان جایگزین می‌شود. پیش از آن یک نسخه پشتیبان خودکار از وضعیت فعلی گرفته می‌شود. ادامه می‌دهید؟' });
    if (!ok) { fileInput.value = ''; return; }
    try { const r = await api.postRaw('/api/backup/restore?confirm=true', text); toast('اطلاعات با موفقیت بازیابی شد.', 'success'); (r?.warnings || []).forEach((w) => toast(w, 'warn', 9000)); await refreshMeta(); reload(); } catch { /* toast نمایش داده شده */ }
    fileInput.value = '';
  });
  return section('پشتیبان‌گیری و بازیابی', h('div', { class: 'page-actions' },
    h('a', { class: 'btn primary', href: '/api/backup/export', download: '' }, icon('download'), 'دریافت پشتیبان JSON'),
    h('button', { class: 'btn', onclick: () => fileInput.click() }, icon('upload'), 'بازیابی از فایل JSON'), fileInput,
    h('button', { class: 'btn', onclick: async () => { const r = await api.post('/api/backup/db'); toast(`نسخه پشتیبان دیتابیس ساخته شد: ${r.files.join('، ')}`, 'success', 7000); reload(); } }, 'نسخه پشتیبان فایل دیتابیس روی سرور')),
    h('p', { class: 'sticky-note' }, 'داده‌ها در دیتابیس سرور ذخیره می‌شوند و با Refresh از بین نمی‌روند. پشتیبان JSON را بیرون از سرور نگه دارید.'),
    backups.length ? h('div', { style: { marginTop: '12px' } }, h('h3', { style: { fontSize: '14px', marginBottom: '6px' } }, 'نسخه‌های پشتیبان روی سرور'), table([
      { label: 'فایل', render: (b) => h('span', { dir: 'ltr' }, b.name) }, { label: 'زمان', render: (b) => fmtDateTime(b.created) }, { label: 'حجم', class: 'num', render: (b) => `${num(Math.round(b.size / 1024))} KB` }], backups.slice(0, 8))) : null);
}

function dangerSection() {
  const start = async (scope) => {
    const ok1 = await confirmDialog({ title: 'مرحله ۱ از ۳', danger: true, confirmLabel: 'ادامه', message: scope === 'all' ? 'تمام اطلاعات شامل تراکنش‌ها، قیمت‌ها، دارایی‌ها و تنظیمات پاک و برنامه به حالت اولیه برمی‌گردد.' : 'تمام تراکنش‌ها، قیمت‌ها و نرخ‌های ارز پاک می‌شود (دارایی‌ها و تنظیمات حفظ می‌شود).' });
    if (!ok1) return;
    const req = await api.post('/api/data/reset/request', { scope });
    const form = formModal({
      title: 'مرحله ۲ از ۳ — تأیید نهایی', submitLabel: 'پاک‌سازی دائمی', wide: false,
      fields: [{ name: 'understand', label: 'می‌دانم این عملیات برگشت‌پذیر نیست (فقط از طریق پشتیبان)', type: 'checkbox', wide: true },
        { name: 'phrase', label: `برای تأیید عبارت «${req.phrase}» را تایپ کنید`, type: 'text', required: true, wide: true }],
      extra: notice('قبل از پاک‌سازی یک نسخه پشتیبان خودکار روی سرور ذخیره می‌شود. بهتر است پشتیبان JSON هم دانلود کنید.', 'warn'),
      onSubmit: async (x, m) => {
        if (!x.understand) throw new Error('لطفاً تیک تأیید را بزنید.');
        const r = await api.post('/api/data/reset/confirm', { token: req.token, phrase: x.phrase, scope });
        m.close(); toast(`پاک‌سازی انجام شد. نسخه پشتیبان: ${r.backup.files.join('، ')}`, 'success', 9000); await refreshMeta(); reload();
      },
    });
  };
  return h('section', { class: 'card danger-zone' }, h('h2', { style: { fontSize: '16px', marginBottom: '8px' } }, 'منطقه خطر — پاک‌سازی اطلاعات'),
    h('p', { class: 'muted', style: { marginTop: 0 } }, 'پاک‌سازی در سه مرحله انجام می‌شود: تأیید، تایپ عبارت امنیتی و اجرای نهایی.'),
    h('div', { class: 'page-actions' }, h('button', { class: 'btn danger', onclick: () => start('data') }, 'پاک‌سازی تراکنش‌ها و قیمت‌ها'), h('button', { class: 'btn danger', onclick: () => start('all') }, 'بازنشانی کامل به حالت اولیه')));
}
