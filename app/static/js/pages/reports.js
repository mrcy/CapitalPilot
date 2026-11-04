import { api, qs } from '../api.js';
import { calendar } from '../state.js';
import { badge, buildForm, clear, h, icon, loadingBox, notice, table, pageHead } from '../ui.js';
import { fmtDate, money, num, pct, units, jalaliYearMonth, todayISO, JALALI_MONTHS, GREG_MONTHS, faDigits } from '../format.js';

const fmtCell = (v, type) => {
  if (v === null || v === undefined || v === '') return '—';
  if (type === 'money') return money(v, 0, false);
  if (type === 'percent') return pct(v, 2);
  if (type === 'units') return units(v);
  if (type === 'number') return num(v, 2);
  if (type === 'date') return fmtDate(v);
  return String(v);
};

export async function render(root) {
  const cat = await api.get('/api/reports');
  let key = 'monthly';
  const [cy, cm] = jalaliYearMonth(todayISO());
  const params = { year: cy, month: cm, quarter: Math.ceil(cm / 3), date: todayISO(), date_from: '', date_to: '' };
  const list = h('div', { class: 'report-list' });
  const paramBox = h('div');
  const paramCard = h('div', { class: 'card', style: { marginBottom: '12px' } }, paramBox);
  const out = h('div', null);
  const names = calendar() === 'jalali' ? JALALI_MONTHS : GREG_MONTHS;

  function drawParams() {
    clear(paramBox);
    const c = cat.find((x) => x.key === key);
    const fields = [];
    if (c.params.includes('date')) fields.push({ name: 'date', label: 'تاریخ', type: 'date' });
    if (c.params.includes('year')) fields.push({ name: 'year', label: 'سال', type: 'int' });
    if (c.params.includes('month')) fields.push({ name: 'month', label: 'ماه', type: 'select', numeric: true, options: names.map((n, i) => ({ value: i + 1, label: n })) });
    if (c.params.includes('quarter')) fields.push({ name: 'quarter', label: 'فصل', type: 'select', numeric: true, options: [1, 2, 3, 4].map((q) => ({ value: q, label: calendar() === 'jalali' ? ['بهار', 'تابستان', 'پاییز', 'زمستان'][q - 1] : `Q${q}` })) });
    if (c.params.includes('date_from')) fields.push({ name: 'date_from', label: 'از تاریخ (اختیاری)', type: 'date', required: false });
    if (c.params.includes('date_to')) fields.push({ name: 'date_to', label: 'تا تاریخ (اختیاری)', type: 'date', required: false });
    paramCard.hidden = !fields.length;
    if (!fields.length) return;
    const f = buildForm(fields, params);
    f.form.className = 'filters';
    f.form.addEventListener('change', () => { Object.assign(params, f.getValues()); run(); });
    f.form.addEventListener('submit', (e) => { e.preventDefault(); Object.assign(params, f.getValues()); run(); });
    paramBox.append(f.form);
  }
  const query = () => {
    const c = cat.find((x) => x.key === key);
    const q = {};
    c.params.forEach((p) => { if (params[p]) q[p] = params[p]; });
    return q;
  };
  function drawList() {
    clear(list);
    cat.forEach((c) => list.append(h('button', { class: key === c.key ? 'active' : '', onclick: () => { key = c.key; drawList(); drawParams(); run(); } }, c.title)));
  }
  async function run() {
    clear(out).append(loadingBox());
    let rep;
    try { rep = await api.get(`/api/reports/${key}`, query()); } catch (e) { clear(out).append(notice(e.message, 'bad')); return; }
    const q = qs(query());
    const exp = (fmt, label) => h('a', { class: 'btn', href: `/api/reports/${key}/export${q ? q + '&' : '?'}format=${fmt}`, download: '' }, icon('download', 16), label);
    clear(out).append(
      h('div', { class: 'card' },
        h('div', { class: 'page-head', style: { marginBottom: '10px' } }, h('div', null, h('h2', null, rep.title), rep.subtitle ? h('p', { class: 'muted', style: { margin: 0 } }, rep.subtitle) : null),
          h('div', { class: 'page-actions' }, exp('xlsx', 'Excel'), exp('csv', 'CSV'), exp('pdf', 'PDF'))),
        rep.notes.map((n) => notice(n, 'info')),
        rep.summary.length ? h('div', { class: 'summary-grid' }, rep.summary.map((s) => h('div', { class: 'summary-item' }, h('span', null, s.label),
          h('b', null, s.value === null || s.value === undefined ? h('small', { class: 'muted' }, s.note || '—') : (s.type === 'text' ? s.value : fmtCell(s.value, s.type) + (s.type === 'money' ? ' تومان' : ''))))))
          : null,
        table(rep.columns.map((c) => ({ label: c.label, class: ['money', 'number', 'units', 'percent'].includes(c.type) ? 'num' : '', render: (r) => fmtCell(r[c.key], c.type) })), rep.rows, { empty: 'داده‌ای برای این گزارش وجود ندارد.' })));
  }
  root.append(pageHead('گزارش‌های مالی', 'خروجی Excel (اعداد واقعی)، CSV و PDF برای همه گزارش‌ها'), h('div', { class: 'report-layout' }, h('div', { class: 'card', style: { alignSelf: 'start' } }, list), h('div', null, paramCard, out)));
  drawList(); drawParams();
  await run();
}
