// فرم مشترک ثبت/ویرایش تراکنش
import { api } from '../api.js';
import { state } from '../state.js';
import { formModal, h, toast, toastWarnings } from '../ui.js';
import { TYPE_LABEL, money, num, todayISO, parseDecimal, units } from '../format.js';

const ASSET_TYPES = ['buy', 'sell'];

export async function openTxForm({ tx = null, defaults = {}, onDone } = {}) {
  const [assetsRes, plan] = await Promise.all([api.get('/api/assets'), api.get('/api/contributions')]);
  // فقط دارایی‌های عضو سبد فعلی (یا دارای موجودی/تراکنش) و غیربایگانی؛ دارایی بایگانی‌شده فقط برای فروش موجودی باقی‌مانده یا ویرایش تراکنش قدیمی
  const assets = assetsRes.assets.filter((a) => (tx && tx.asset_id === a.id) || (!a.is_archived && a.is_active && a.in_portfolio) || (a.is_archived && Number(a.position?.units) > 0));
  const platforms = state.meta.platforms.filter((p) => (p.is_active && !p.is_archived) || (tx && tx.platform_id === p.id));
  const byId = Object.fromEntries(assets.map((a) => [a.id, a]));
  const periodLabel = (p) => (p.seq === 0 ? 'سرمایه اولیه' : `واریزی ماه ${num(p.seq)}`) + ` — ${p.label}`;
  const v = { tx_type: 'buy', tx_date: todayISO(), record_price: true, ...defaults, ...(tx ? {
    tx_type: tx.tx_type, tx_date: tx.tx_date, platform_id: tx.platform_id, asset_id: tx.asset_id, quantity: tx.quantity, unit_price: tx.unit_price,
    fee: Number(tx.fee) ? tx.fee : '', amount: ['buy', 'sell'].includes(tx.tx_type) || tx.tx_type === 'adjustment' && tx.asset_id ? '' : (tx.tx_type === 'dividend' ? Number(tx.total_amount) + Number(tx.fee) : tx.total_amount),
    fx_rate: tx.fx_rate, plan_period_id: tx.plan_period_id, note: tx.note, record_price: false } : {}) };
  const isTrade = (x) => ASSET_TYPES.includes(x.tx_type);
  const hasAsset = (x) => isTrade(x) || (['dividend', 'fee', 'adjustment'].includes(x.tx_type) && x.asset_id);
  const foreign = (x) => x.asset_id && byId[x.asset_id] && byId[x.asset_id].price_currency !== 'IRT';
  const fields = [
    { name: 'tx_type', label: 'نوع تراکنش', type: 'select', required: true, options: Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label })) },
    { name: 'tx_date', label: 'تاریخ', type: 'date', required: true },
    { name: 'asset_id', label: 'دارایی', type: 'select', numeric: true, required: false,
      show: (x) => !['deposit', 'withdrawal'].includes(x.tx_type), options: [{ value: '', label: '— انتخاب کنید —' }, ...assets.map((a) => ({ value: a.id, label: `${a.name} (${a.platform})${a.is_archived ? ' — بایگانی' : ''}` }))] },
    { name: 'platform_id', label: 'پلتفرم', type: 'select', numeric: true, required: false,
      show: (x) => ['deposit', 'withdrawal'].includes(x.tx_type) || (['dividend', 'fee', 'adjustment'].includes(x.tx_type) && !x.asset_id),
      options: platforms.map((p) => ({ value: p.id, label: p.name })) },
    { name: 'quantity', label: 'تعداد واحد', type: 'decimal', show: (x) => isTrade(x) || (x.tx_type === 'adjustment' && x.asset_id), hint: (tx && tx.tx_type === 'adjustment') || defaults.tx_type === 'adjustment' ? 'برای کسر موجودی عدد منفی وارد کنید.' : undefined },
    { name: 'unit_price', label: 'قیمت هر واحد (تومان)', type: 'decimal', show: (x) => isTrade(x) || (x.tx_type === 'adjustment' && x.asset_id && !(Number(x.quantity) < 0)) },
    { name: 'fee', label: 'کارمزد (تومان)', type: 'decimal', show: (x) => isTrade(x) || x.tx_type === 'dividend', hint: 'در خرید به بهای تمام‌شده اضافه و در فروش از درآمد کم می‌شود.' },
    { name: 'amount', label: 'مبلغ (تومان)', type: 'decimal', show: (x) => ['deposit', 'withdrawal', 'dividend', 'fee'].includes(x.tx_type) || (x.tx_type === 'adjustment' && !x.asset_id),
      hint: 'برای اصلاح نقدینگی می‌توانید عدد منفی وارد کنید.' },
    { name: 'fx_rate', label: 'نرخ ارز در لحظه تراکنش (تومان)', type: 'decimal', show: (x) => foreign(x) && (isTrade(x) || x.tx_type === 'adjustment'), hint: 'اختیاری؛ برای تفکیک اثر نرخ ارز از اثر قیمت لازم است.' },
    { name: 'plan_period_id', label: 'دوره برنامه واریزی', type: 'select', numeric: true, show: (x) => x.tx_type === 'deposit',
      options: [{ value: '', label: 'خارج از برنامه (اضافه‌واریزی)' }, ...plan.periods.map((p) => ({ value: p.id, label: periodLabel(p) }))] },
    { name: 'record_price', label: 'قیمت واحد را به‌عنوان قیمت روز دارایی ثبت کن', type: 'checkbox', show: (x) => !tx && isTrade(x) && !!x.asset_id },
    { name: 'note', label: 'توضیحات', type: 'textarea', wide: true },
  ];
  const preview = h('div', { class: 'notice info' });
  const update = (x) => {
    let txt = '';
    const q = parseDecimal(x.quantity ?? ''), p = parseDecimal(x.unit_price ?? ''), f = Number(x.fee || 0) || 0;
    if (isTrade(x) && x.quantity && x.unit_price && !Number.isNaN(Number(x.quantity)) && !Number.isNaN(Number(x.unit_price))) {
      const gross = Number(x.quantity) * Number(x.unit_price);
      txt = `پیش‌نمایش مبلغ نهایی: ${money(x.tx_type === 'buy' ? gross + f : gross - f)} (مقدار قطعی را سرور محاسبه می‌کند)`;
    }
    preview.textContent = txt; preview.hidden = !txt;
  };
  const initial = { ...v, asset_id: v.asset_id ?? '', platform_id: v.platform_id ?? platforms[0]?.id, plan_period_id: v.plan_period_id ?? '' };
  const form = formModal({
    title: tx ? `ویرایش تراکنش #${num(tx.id)}` : 'ثبت تراکنش جدید', fields, values: initial, wide: true, extra: preview,
    submitLabel: tx ? 'ذخیره تغییرات' : 'ثبت تراکنش',
    onChange: (x) => update(x),
    onSubmit: async (x, m) => {
      const body = { tx_date: x.tx_date, tx_type: x.tx_type, note: x.note || '' };
      const t = x.tx_type;
      if (!['deposit', 'withdrawal'].includes(t) && x.asset_id) body.asset_id = x.asset_id;
      if (['deposit', 'withdrawal'].includes(t) || !x.asset_id) body.platform_id = x.platform_id;
      if (isTrade(x) || (t === 'adjustment' && x.asset_id)) { body.quantity = x.quantity; if (t !== 'adjustment' || !(Number(x.quantity) < 0)) body.unit_price = x.unit_price; }
      if (isTrade(x) || t === 'dividend') body.fee = x.fee ?? '0';
      if (['deposit', 'withdrawal', 'dividend', 'fee'].includes(t) || (t === 'adjustment' && !x.asset_id)) body.amount = x.amount;
      if (foreign(x) && x.fx_rate) body.fx_rate = x.fx_rate;
      if (t === 'deposit' && x.plan_period_id) body.plan_period_id = x.plan_period_id;
      if (!tx && isTrade(x) && x.record_price) body.record_price = true;
      for (const k of ['quantity', 'unit_price', 'fee', 'amount', 'fx_rate']) if (body[k] !== undefined && (body[k] === null || Number.isNaN(body[k]))) delete body[k];
      const res = tx ? await api.put(`/api/transactions/${tx.id}`, body) : await api.post('/api/transactions', body);
      m.close();
      toast(tx ? 'تراکنش ویرایش شد و محاسبات به‌روزرسانی شد.' : 'تراکنش ثبت شد.', 'success');
      toastWarnings(res.warnings);
      onDone && onDone(res);
    },
  });
  return form;
}
