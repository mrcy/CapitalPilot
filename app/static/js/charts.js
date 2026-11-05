// تنظیمات و ابزارهای نمودار (Chart.js، نسخه محلی بدون CDN)
import { compact, fmtDate, money, num, pct, isNil } from './format.js';
import { typeColor } from './ui.js';

export const COLORS = {
  green: '#2fd29a', red: '#ff5d73', gold: '#e8b84a', blue: '#4aa3ff', indigo: '#6f86ff', teal: '#34c5c0',
  slate: '#8d9bb8', grid: 'rgba(140,160,205,.10)', text: '#9fb0d0',
};
// رنگ نوع دارایی از تنظیمات نوع (پویا) خوانده می‌شود
export const TYPE_COLOR = new Proxy({}, { get: (_, k) => (k === 'cash' ? '#5f6f91' : typeColor(String(k))) });
const live = new Map();

export function setupCharts() {
  const C = window.Chart;
  if (!C) return;
  C.defaults.font.family = 'Vazirmatn, Tahoma, sans-serif';
  C.defaults.font.size = 12;
  C.defaults.color = COLORS.text;
  C.defaults.borderColor = COLORS.grid;
  C.defaults.maintainAspectRatio = false;
  C.defaults.plugins.legend.rtl = true;
  C.defaults.plugins.legend.labels.usePointStyle = true;
  C.defaults.plugins.legend.labels.boxWidth = 8;
  C.defaults.plugins.tooltip.rtl = true;
  C.defaults.plugins.tooltip.textDirection = 'rtl';
  C.defaults.plugins.tooltip.backgroundColor = 'rgba(8,14,30,.96)';
  C.defaults.plugins.tooltip.borderColor = 'rgba(140,160,205,.25)';
  C.defaults.plugins.tooltip.borderWidth = 1;
  C.defaults.plugins.tooltip.padding = 10;
  C.defaults.animation.duration = 500;
}

export function destroyAll() { for (const c of live.values()) c.destroy(); live.clear(); }

export function chartCard(title, build, { sub, tall = false } = {}) {
  const card = document.createElement('div');
  card.className = 'card chart-card';
  const head = document.createElement('div');
  head.className = 'chart-head';
  head.innerHTML = `<h3></h3>${sub ? '<small class="muted"></small>' : ''}`;
  head.querySelector('h3').textContent = title;
  if (sub) head.querySelector('small').textContent = sub;
  const box = document.createElement('div');
  box.className = `chart-box ${tall ? 'tall' : ''}`;
  card.append(head, box);
  // ساخت پس از افزودن به DOM
  queueMicrotask(() => {
    const cfg = build();
    if (!cfg) { box.innerHTML = '<div class="chart-empty">داده‌ای برای نمایش وجود ندارد.<br><small>پس از ثبت تراکنش و قیمت معتبر، نمودار فعال می‌شود.</small></div>'; return; }
    const canvas = document.createElement('canvas');
    box.append(canvas);
    const ch = new window.Chart(canvas, cfg);
    live.set(canvas, ch);
  });
  return card;
}

const axisBase = () => ({
  grid: { color: COLORS.grid }, border: { display: false },
  ticks: { color: COLORS.text, maxRotation: 0, autoSkipPadding: 18 },
});
const catAxis = () => ({ ...axisBase(), ticks: { color: COLORS.text, autoSkip: false, maxRotation: 0 } });
const moneyAxis = () => ({ ...axisBase(), position: 'right', ticks: { color: COLORS.text, callback: (v) => compact(v) } });
const moneyTip = (ctx) => ` ${ctx.dataset.label ? ctx.dataset.label + ': ' : ''}${money(ctx.parsed.y ?? ctx.parsed)}`;

export function lineConfig(points, series, { yFmt = 'money', area = false, yReverse = false, suggestedMax } = {}) {
  if (!points || points.length < 1) return null;
  const labels = points.map((p) => fmtDate(p.date));
  const datasets = series.map((s) => ({
    label: s.label, data: points.map((p) => (isNil(p[s.key]) ? null : Number(p[s.key]))), borderColor: s.color, backgroundColor: s.fill || 'transparent',
    fill: s.fill ? 'origin' : false, tension: 0.25, borderWidth: 2, pointRadius: points.length > 40 ? 0 : 3, pointHoverRadius: 5, spanGaps: true, stepped: s.stepped || false,
  }));
  return {
    type: 'line', data: { labels, datasets },
    options: {
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: series.length > 1 }, tooltip: { callbacks: { label: yFmt === 'pct' ? (c) => ` ${c.dataset.label}: ${pct(c.parsed.y)}` : moneyTip } } },
      scales: { x: axisBase(), y: yFmt === 'pct' ? { ...axisBase(), position: 'right', reverse: yReverse, suggestedMax, ticks: { color: COLORS.text, callback: (v) => pct(v, 0) } } : moneyAxis() },
    },
  };
}

export function doughnutConfig(items, colorOf) {
  if (!items.length) return null;
  return {
    type: 'doughnut',
    data: { labels: items.map((i) => i.name), datasets: [{ data: items.map((i) => Number(i.value)), backgroundColor: items.map(colorOf), borderColor: '#101b33', borderWidth: 3, hoverOffset: 6 }] },
    options: { cutout: '64%', plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => ` ${c.label}: ${money(c.parsed)}` } } } },
  };
}

export function barConfig(labels, values, { fmt = 'pct', colorFn, label = '', horizontal = false } = {}) {
  if (!labels.length) return null;
  const f = fmt === 'pct' ? (v) => pct(v) : (v) => money(v);
  return {
    type: 'bar',
    data: { labels, datasets: [{ label, data: values.map(Number), backgroundColor: values.map((v, i) => (colorFn ? colorFn(v, i) : Number(v) >= 0 ? COLORS.green : COLORS.red)), borderRadius: 6, maxBarThickness: 38 }] },
    options: {
      indexAxis: horizontal ? 'y' : 'x',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${f(horizontal ? c.parsed.x : c.parsed.y)}` } } },
      scales: {
        x: horizontal ? { ...axisBase(), ticks: { color: COLORS.text, callback: (v) => (fmt === 'pct' ? pct(v, 1) : compact(v)) } } : catAxis(),
        y: horizontal ? { ...axisBase(), position: 'right' } : { ...axisBase(), position: 'right', ticks: { color: COLORS.text, callback: (v) => (fmt === 'pct' ? pct(v, 1) : compact(v)) } },
      },
    },
  };
}

export function groupedBarConfig(labels, sets, { fmt = 'money' } = {}) {
  if (!labels.length) return null;
  return {
    type: 'bar',
    data: { labels, datasets: sets.map((s) => ({ label: s.label, data: s.data.map(Number), backgroundColor: s.color, borderRadius: 5, maxBarThickness: 26 })) },
    options: {
      plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt === 'pct' ? pct(c.parsed.y) : money(c.parsed.y)}` } } },
      scales: { x: catAxis(), y: { ...axisBase(), position: 'right', ticks: { color: COLORS.text, callback: (v) => (fmt === 'pct' ? pct(v, 1) : compact(v)) } } },
    },
  };
}
