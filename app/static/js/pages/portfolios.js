import { api } from '../api.js';
import { setPortfolio, state } from '../state.js';
import { reloadAll } from '../app.js';
import { badge, clear, confirmDialog, formModal, h, icon, modal, notice, pageHead, toast, typeDot } from '../ui.js';
import { fmtDate, money, num, pct, parseDecimal, faDigits } from '../format.js';

const MODE = { percent: 'درصدی (مجموع ۱۰۰٪)', amount: 'مبلغ ثابت' };

export function openPortfolioForm({ portfolio = null, onDone } = {}) {
  return formModal({
    title: portfolio ? `ویرایش «${portfolio.name}»` : 'سبد / استراتژی جدید', wide: true,
    fields: [
      { name: 'name', label: 'نام سبد', type: 'text', required: true },
      { name: 'target_mode', label: 'حالت وزن هدف', type: 'select', options: Object.entries(MODE).map(([value, label]) => ({ value, label })) },
      { name: 'initial_capital', label: 'سرمایه اولیه (تومان)', type: 'decimal', required: true },
      { name: 'monthly_contribution', label: 'واریزی ماهانه (تومان)', type: 'decimal', required: true },
      { name: 'horizon_months', label: 'افق سرمایه‌گذاری (ماه)', type: 'int', required: true },
      { name: 'max_drawdown_pct', label: 'حداکثر افت قابل تحمل (٪)', type: 'decimal', required: true },
      { name: 'plan_start_date', label: 'تاریخ شروع', type: 'date' },
      ...(portfolio ? [{ name: 'apply_to_past_unpaid', label: 'تغییر مبلغ، دوره‌های گذشتهٔ پرداخت‌نشده را هم به‌روز کند', type: 'checkbox', wide: true }] : []),
      { name: 'description', label: 'توضیحات و استراتژی', type: 'textarea', wide: true },
    ],
    values: portfolio ? { ...portfolio, apply_to_past_unpaid: false } : { target_mode: 'percent', initial_capital: '0', monthly_contribution: '0', horizon_months: 12, max_drawdown_pct: '25' },
    onSubmit: async (x, m) => {
      const body = { name: x.name.trim(), description: x.description || '', initial_capital: x.initial_capital ?? '0', monthly_contribution: x.monthly_contribution ?? '0',
        horizon_months: x.horizon_months, max_drawdown_pct: x.max_drawdown_pct, plan_start_date: x.plan_start_date, target_mode: x.target_mode, apply_to_past_unpaid: !!x.apply_to_past_unpaid };
      const res = portfolio ? await api.put(`/api/portfolios/${portfolio.id}`, body) : await api.post('/api/portfolios', body);
      m.close(); toast('سبد ذخیره شد.', 'success'); onDone && onDone(res);
    },
  });
}

/** ویرایش اعضا و وزن‌های هدف؛ حذف عضو، تراکنش‌ها را حذف نمی‌کند. */
export async function openMembersEditor(pfId, onDone) {
  const pf = await api.get(`/api/portfolios/${pfId}`);
  const catalog = (await api.get('/api/assets', { status: 'live', page_size: 500, portfolio_id: pfId })).assets;
  let members = pf.members.map((x) => ({ asset_id: x.asset_id, name: x.name, platform: x.platform, asset_type: x.asset_type, w: String(x.target_weight), amt: String(x.target_amount), active: x.is_active, archived: x.asset_archived }));
  const isPct = pf.target_mode === 'percent';
  const listBox = h('div');
  const sum = h('b');
  const sumBox = h('div', { class: 'inline-form', style: { margin: '8px 0' } }, h('span', { class: 'muted' }, isPct ? 'مجموع وزن‌های فعال:' : 'مجموع مبالغ هدف:'), sum);
  const picker = h('select', { 'aria-label': 'افزودن دارایی' });
  const drawPicker = () => {
    const free = catalog.filter((a) => !members.some((x) => x.asset_id === a.id) && a.is_active);
    clear(picker).append(h('option', { value: '' }, free.length ? 'افزودن دارایی به سبد…' : 'دارایی دیگری برای افزودن نیست'), ...free.map((a) => h('option', { value: a.id }, `${a.name} — ${a.platform}`)));
  };
  const val = (v) => { const n = Number(parseDecimal(v)); return Number.isFinite(n) ? n : 0; };
  const redraw = () => {
    clear(listBox);
    members.forEach((mb) => {
      const inp = h('input', { type: 'text', inputmode: 'decimal', dir: 'ltr', class: 'ltr-input', value: faDigits(isPct ? mb.w : mb.amt), 'aria-label': `${isPct ? 'وزن' : 'مبلغ'} ${mb.name}` });
      inp.addEventListener('input', () => { mb[isPct ? 'w' : 'amt'] = inp.value; total(); });
      const act = h('input', { type: 'checkbox', checked: mb.active, 'aria-label': `فعال ${mb.name}`, title: 'فعال در پیشنهاد خرید' });
      act.addEventListener('change', () => { mb.active = act.checked; total(); });
      listBox.append(h('div', { class: 'member-row' },
        h('div', null, h('b', null, typeDot(mb.asset_type), mb.name), mb.archived ? badge('بایگانی') : '', h('div', { class: 'muted', style: { fontSize: '12px' } }, mb.platform)),
        h('div', null, inp, h('small', { class: 'hint' }, isPct ? 'درصد' : 'تومان')),
        h('div', { class: 'row-actions' }, h('label', { class: 'check', title: 'فعال' }, act),
          h('button', { class: 'icon-btn', type: 'button', title: 'حذف از سبد', 'aria-label': `حذف ${mb.name} از سبد`, onclick: () => { members = members.filter((x) => x !== mb); redraw(); drawPicker(); } }, icon('trash', 16)))));
    });
    if (!members.length) listBox.append(h('p', { class: 'muted' }, 'سبد هنوز دارایی ندارد.'));
    total();
  };
  const total = () => {
    const act = members.filter((x) => x.active);
    const s = act.reduce((a, x) => a + val(isPct ? x.w : x.amt), 0);
    sum.textContent = isPct ? `${num(Math.round(s * 100) / 100)}٪` : money(s);
    sum.className = isPct ? (Math.abs(s - 100) < 0.0001 || !act.length ? 'pos' : 'neg') : '';
  };
  picker.addEventListener('change', () => {
    const a = catalog.find((x) => String(x.id) === picker.value);
    if (!a) return;
    members.push({ asset_id: a.id, name: a.name, platform: a.platform, asset_type: a.asset_type, w: '0', amt: '0', active: true });
    redraw(); drawPicker();
  });
  const err = h('div', { class: 'form-error', hidden: true });
  const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    save.disabled = true; err.hidden = true;
    try {
      const body = { members: members.map((x) => ({ asset_id: x.asset_id, target_weight: isPct ? String(parseDecimal(x.w) || 0) : '0', target_amount: isPct ? '0' : String(parseDecimal(x.amt) || 0), is_active: x.active })) };
      const r = await api.put(`/api/portfolios/${pfId}/targets`, body, { silent: true });
      r.warnings.forEach((w) => toast(w, 'warn', 8000));
      m.close(); toast('اعضا و وزن‌ها ذخیره شد.', 'success'); onDone();
    } catch (e) { err.textContent = e.message; err.hidden = false; save.disabled = false; }
  } }, 'ذخیره');
  const m = modal({ title: `دارایی‌ها و وزن هدف «${pf.name}»`, wide: true, body: [
    notice(isPct ? 'مجموع وزن دارایی‌های فعال باید دقیقاً ۱۰۰٪ باشد.' : 'در حالت مبلغ ثابت، وزن مؤثر از نسبت مبلغ هر دارایی به مجموع محاسبه می‌شود.', 'info'),
    notice('حذف دارایی از سبد، تراکنش‌ها و تاریخچهٔ آن را پاک نمی‌کند؛ فقط از اهداف و پیشنهاد خرید این سبد خارج می‌شود.', 'info'),
    h('div', { class: 'inline-form' }, h('label', { style: { flex: 1 } }, picker)), sumBox, listBox, err],
  footer: [h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'انصراف'), save] });
  drawPicker(); redraw();
}

async function deletePortfolio(p, done) {
  if (p.is_default) { toast('سبد پیش‌فرض قابل حذف نیست.', 'warn'); return; }
  if (p.transaction_count) {
    if (await confirmDialog({ title: 'حذف ممکن نیست', message: `«${p.name}» دارای ${num(p.transaction_count)} تراکنش است و فقط قابل بایگانی است. بایگانی شود؟`, confirmLabel: 'بایگانی' })) { await api.post(`/api/portfolios/${p.id}/archive`); toast('سبد بایگانی شد.', 'success'); done(); }
    return;
  }
  if (await confirmDialog({ title: 'حذف سبد', message: `«${p.name}» بدون تراکنش است و برای همیشه حذف می‌شود (دارایی‌ها دست‌نخورده می‌مانند).`, danger: true, confirmLabel: 'حذف' })) { await api.del(`/api/portfolios/${p.id}`); toast('سبد حذف شد.', 'success'); done(); }
}

export async function render(root) {
  root.append(pageHead('سبدها و استراتژی‌ها', 'چند سبد مستقل با سرمایه، افق، دارایی‌ها و وزن‌های هدف جداگانه بسازید. تراکنش‌ها و گزارش‌ها برای هر سبد جدا محاسبه می‌شود.',
    h('button', { class: 'btn primary', onclick: () => openPortfolioForm({ onDone: async (pf) => { await reloadAll(); if (pf?.id) openMembersEditor(pf.id, reloadAll); } }) }, icon('plus'), 'سبد جدید')));
  const list = await api.get('/api/portfolios');
  const done = () => reloadAll();
  root.append(h('div', { class: 'stack-cards two' }, list.map((p) => {
    const active = p.id === state.portfolioId;
    return h('div', { class: `card mcard ${p.is_archived ? 'archived' : ''}` },
      h('h3', null, p.name, p.is_default ? badge('پیش‌فرض', 'info') : '', p.is_archived ? badge('بایگانی‌شده') : '', active ? badge('سبد فعال', 'ok') : ''),
      p.description ? h('div', { class: 'muted' }, p.description) : null,
      h('div', { class: 'kv' },
        h('div', null, h('span', null, 'سرمایه اولیه'), h('b', null, money(p.initial_capital))),
        h('div', null, h('span', null, 'واریزی ماهانه'), h('b', null, money(p.monthly_contribution))),
        h('div', null, h('span', null, 'افق'), h('b', null, `${num(p.horizon_months)} ماه`)),
        h('div', null, h('span', null, 'حداکثر افت قابل تحمل'), h('b', null, pct(p.max_drawdown_pct, 0))),
        h('div', null, h('span', null, 'شروع برنامه'), h('b', null, fmtDate(p.plan_start_date))),
        h('div', null, h('span', null, 'هدف کل برنامه'), h('b', null, money(p.plan_target_total)))),
      h('div', { class: 'meta' }, h('span', null, `${num(p.active_member_count)} دارایی فعال از ${num(p.member_count)}`), h('span', null, `${num(p.transaction_count)} تراکنش`), h('span', null, MODE[p.target_mode]),
        p.targets_ok ? badge(p.target_mode === 'percent' ? 'مجموع وزن‌ها ۱۰۰٪' : 'مبالغ هدف تنظیم شده', 'ok') : badge(p.target_mode === 'percent' ? `مجموع وزن‌ها ${num(p.target_total)}٪` : 'مبلغ هدف تنظیم نشده', 'warn')),
      h('div', { class: 'actions' },
        p.is_archived ? null : h('button', { class: 'btn tiny primary', disabled: active, onclick: async () => { setPortfolio(p.id); await reloadAll(); toast(`سبد «${p.name}» فعال شد.`, 'success'); } }, active ? 'در حال استفاده' : 'انتخاب به‌عنوان سبد فعال'),
        p.is_archived ? null : h('button', { class: 'btn tiny', onclick: () => openMembersEditor(p.id, done) }, icon('assets', 14), 'دارایی‌ها و وزن‌ها'),
        p.is_archived ? null : h('button', { class: 'btn tiny', onclick: () => openPortfolioForm({ portfolio: p, onDone: done }) }, icon('edit', 14), 'ویرایش'),
        p.is_default || p.is_archived ? null : h('button', { class: 'btn tiny', onclick: async () => { await api.post(`/api/portfolios/${p.id}/make-default`); toast('به‌عنوان سبد پیش‌فرض تنظیم شد.', 'success'); done(); } }, 'پیش‌فرض شود'),
        p.is_archived ? h('button', { class: 'btn tiny', onclick: async () => { await api.post(`/api/portfolios/${p.id}/restore`); toast('بازیابی شد.', 'success'); done(); } }, icon('restore', 14), 'بازیابی')
          : (p.is_default ? null : h('button', { class: 'btn tiny', onclick: async () => { if (await confirmDialog({ message: `«${p.name}» بایگانی شود؟ تراکنش‌ها حفظ می‌شود.`, confirmLabel: 'بایگانی' })) { await api.post(`/api/portfolios/${p.id}/archive`); toast('بایگانی شد.', 'success'); done(); } } }, icon('archive', 14), 'بایگانی')),
        p.is_default ? null : h('button', { class: 'btn tiny danger', onclick: () => deletePortfolio(p, done) }, icon('trash', 14), 'حذف')));
  })));
}
