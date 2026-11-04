// قالب‌بندی اعداد، پول و تاریخ (فارسی، جداکننده هزارگان)
import { state, calendar, unitLabel } from './state.js';
import { toJalali, toGregorian, isValidJalali } from './jalali.js';

const faNF = (dp) => new Intl.NumberFormat('fa-IR', { maximumFractionDigits: dp, minimumFractionDigits: 0 });
const cache = {};
const nfRaw = (dp) => (cache[dp] ||= faNF(dp));
// عدد را در یک ایزوله چپ‌به‌راست قرار می‌دهیم تا علامت منفی/مثبت و درصد در متن راست‌به‌چپ جابه‌جا نشوند
const LRI = '\u2066', PDI = '\u2069';
const nf = (dp) => ({ format: (x) => LRI + nfRaw(dp).format(x).replace(/\u200e/g, '') + PDI });

export const JALALI_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
export const GREG_MONTHS = ['ژانویه', 'فوریه', 'مارس', 'آوریل', 'مه', 'ژوئن', 'ژوئیه', 'اوت', 'سپتامبر', 'اکتبر', 'نوامبر', 'دسامبر'];

export const isNil = (v) => v === null || v === undefined || v === '' || Number.isNaN(v);
export const n = (v) => (isNil(v) ? null : Number(v));

export function enDigits(s) {
  return String(s ?? '')
    .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d))
    .replace(/[٬,،]/g, '').replace(/٫/g, '.').replace(/[−–]/g, '-').trim();
}
// ورودی کاربر را به رشته اعشاری استاندارد تبدیل می‌کند (یا null اگر خالی/نامعتبر)
export function parseDecimal(s) {
  const t = enDigits(s);
  if (t === '') return null;
  if (!/^-?\d+(\.\d+)?$/.test(t)) return NaN;
  return t;
}

export const num = (v, dp = 0) => (isNil(v) ? '—' : nf(dp).format(Number(v)));
export const units = (v) => (isNil(v) ? '—' : nf(6).format(Number(v)));
export function money(v, dp = 0, withUnit = true) {
  if (isNil(v)) return '—';
  return nf(dp).format(Number(v)) + (withUnit ? ` ${unitLabel()}` : '');
}
export const pct = (v, dp = 2) => (isNil(v) ? '—' : `${LRI}${nfRaw(dp).format(Number(v)).replace(/\u200e/g, '')}٪${PDI}`);
export const signedPct = (v, dp = 2) => (isNil(v) ? '—' : `${LRI}${Number(v) > 0 ? '+' : ''}${nfRaw(dp).format(Number(v)).replace(/\u200e/g, '')}٪${PDI}`);
export const signedMoney = (v, dp = 0) => (isNil(v) ? '—' : `${LRI}${Number(v) > 0 ? '+' : ''}${nfRaw(dp).format(Number(v)).replace(/\u200e/g, '')}${PDI} ${unitLabel()}`);
export const pnlClass = (v) => (isNil(v) || Number(v) === 0 ? '' : Number(v) > 0 ? 'pos' : 'neg');

export function compact(v) {
  if (isNil(v)) return '';
  const a = Math.abs(Number(v)), s = Number(v) < 0 ? '-' : '';
  if (a >= 1e12) return s + nf(2).format(a / 1e12) + ' تریلیون';
  if (a >= 1e9) return s + nf(2).format(a / 1e9) + ' میلیارد';
  if (a >= 1e6) return s + nf(2).format(a / 1e6) + ' میلیون';
  if (a >= 1e3) return s + nf(1).format(a / 1e3) + ' هزار';
  return s + nf(0).format(a);
}

// ---------- تاریخ ----------
export function parseISO(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}
export function fmtDate(iso, cal = calendar()) {
  const p = parseISO(iso);
  if (!p) return '—';
  if (cal === 'jalali') { const [y, m, d] = toJalali(...p); return faDigits(`${y}/${String(m).padStart(2, '0')}/${String(d).padStart(2, '0')}`); }
  return faDigits(iso.slice(0, 10));
}
export const fmtDateTime = (iso) => (iso ? `${fmtDate(iso)} ${faDigits(String(iso).slice(11, 16))}` : '—');
export const faDigits = (s) => String(s).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
export const todayISO = () => state.meta?.today || new Date().toISOString().slice(0, 10);
export function monthLabel(iso) {
  const p = parseISO(iso);
  if (!p) return '';
  if (calendar() === 'jalali') { const [y, m] = toJalali(...p); return `${JALALI_MONTHS[m - 1]} ${faDigits(y)}`; }
  return `${GREG_MONTHS[p[1] - 1]} ${faDigits(p[0])}`;
}
// ورودی تاریخ شمسی/میلادی کاربر → ISO میلادی یا null
export function dateInputToISO(text, cal = calendar()) {
  const t = enDigits(text).replace(/[.\-]/g, '/');
  const m = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(t);
  if (!m) return null;
  let [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (cal === 'jalali') {
    if (!isValidJalali(y, mo, d)) return null;
    [y, mo, d] = toGregorian(y, mo, d);
  } else {
    const dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
  }
  return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}
export function isoToDateInput(iso, cal = calendar()) {
  const p = parseISO(iso);
  if (!p) return '';
  if (cal === 'jalali') { const [y, m, d] = toJalali(...p); return `${y}/${String(m).padStart(2, '0')}/${String(d).padStart(2, '0')}`; }
  return iso.slice(0, 10);
}
export function addDaysISO(iso, days) {
  const [y, m, d] = parseISO(iso);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}
export function jalaliYearMonth(iso) {
  const p = parseISO(iso || todayISO());
  return calendar() === 'jalali' ? toJalali(...p).slice(0, 2) : [p[0], p[1]];
}

export const TYPE_LABEL = { buy: 'خرید', sell: 'فروش', deposit: 'واریز سرمایه', withdrawal: 'برداشت سرمایه', dividend: 'سود نقدی', fee: 'کارمزد', adjustment: 'اصلاح موجودی' };
// برچسب نوع دارایی پویا است: پس از بارگذاری meta از سرور پر می‌شود و نوع‌های تعریف‌شده توسط کاربر را هم شامل می‌شود.
const _typeLabels = { cash: 'نقد' };
export const ASSET_TYPE_LABEL = new Proxy(_typeLabels, { get: (t, k) => (typeof k === 'string' ? (t[k] ?? k) : t[k]) });
export function setAssetTypes(list) { Object.keys(_typeLabels).forEach((k) => delete _typeLabels[k]); _typeLabels.cash = 'نقد'; (list || []).forEach((t) => { _typeLabels[t.key] = t.label; }); }
export const PROVIDER_STATUS = { ok: ['سالم', 'ok'], error: ['خطا', 'bad'], unknown: ['آزمایش‌نشده', 'warn'], disabled: ['غیرفعال', ''], archived: ['بایگانی', ''] };
export const REASON_LABEL = { no_price: 'قیمتی ثبت نشده', stale: 'قیمت قدیمی', currency_mismatch: 'ناهم‌خوانی واحد پول', no_fx: 'نرخ ارز ثبت نشده', stale_fx: 'نرخ ارز قدیمی', conflict: 'اختلاف منابع' };
// وضعیت کیفیت قیمت (لایهٔ کنترل کیفیت) و منشأ قیمت
export const PRICE_STATUS = { valid: ['معتبر', 'ok'], stale: ['قدیمی', 'warn'], invalid: ['نامعتبر', 'bad'], manual: ['دستی', 'gold'], missing: ['ناموجود', ''], conflict: ['اختلاف منابع', 'bad'], pending: ['در انتظار تأیید', 'warn'] };
export const ORIGIN = { manual: ['دستی', 'gold'], online: ['آنلاین', 'blue'] };
export const FLAG_LABEL = { jump: 'تغییر شدید نسبت به قیمت قبلی', time_lag: 'فاصلهٔ زیاد زمان منبع با زمان دریافت', no_source_time: 'منبع زمان قیمت را اعلام نکرده (زمان دریافت جایگزین شد)', future_time: 'زمان قیمت در آینده است', stale: 'قیمت قدیمی', non_positive: 'قیمت صفر، منفی یا نامعتبر', unit_converted: 'واحد قیمت تبدیل شد' };
export const STATUS_LABEL = { paid: 'پرداخت‌شده', extra: 'اضافه‌واریزی', partial: 'ناقص', partial_overdue: 'ناقص و عقب‌افتاده', overdue: 'عقب‌افتاده', due: 'موعد امروز', upcoming: 'در انتظار' };
