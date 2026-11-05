// لایه ارتباط با Backend (REST). تمام محاسبات مالی در سرور انجام می‌شود.
import { toast } from './ui.js';
import { state } from './state.js';

// نقطه‌های انتهایی که به سبد انتخاب‌شده وابسته‌اند؛ شناسهٔ سبد خودکار اضافه می‌شود.
const SCOPED = ['/api/dashboard', '/api/portfolio', '/api/risk', '/api/rebalance', '/api/contributions', '/api/transactions', '/api/assets', '/api/reports'];
const isScoped = (url) => SCOPED.some((p) => url === p || url.startsWith(p + '/') || url.startsWith(p + '?')) && !/\/api\/assets\/\d+\/(purge|price|archive|restore|active|dependencies|refresh)/.test(url);

export class ApiError extends Error {
  constructor(message, status, code, details) { super(message); this.status = status; this.code = code; this.details = details; }
}

async function request(method, url, body, opts = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    if (opts.raw) { init.body = body; init.headers['Content-Type'] = 'application/json'; }
    else { init.body = JSON.stringify(body); init.headers['Content-Type'] = 'application/json'; }
  }
  let res;
  try { res = await fetch(url, init); }
  catch (e) {
    const err = new ApiError('ارتباط با سرور برقرار نشد. اجرای برنامه و اتصال شبکه را بررسی کنید.', 0, 'network');
    if (!opts.silent) toast(err.message, 'error');
    throw err;
  }
  if (res.status === 204) return null;
  let data = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) data = await res.json();
  if (!res.ok) {
    const e = data?.error || {};
    const err = new ApiError(e.message || `خطای سرور (${res.status})`, res.status, e.code, e.details);
    if (!opts.silent) toast(err.message, 'error');
    throw err;
  }
  return data;
}

export function qs(params = {}) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.append(k, v);
  const s = u.toString();
  return s ? `?${s}` : '';
}

const scope = (url, params) => (state.portfolioId && isScoped(url) && !(params && 'portfolio_id' in params) ? { ...params, portfolio_id: state.portfolioId } : params);
export const api = {
  get: (url, params, opts) => request('GET', url + qs(scope(url, params)), undefined, opts),
  post: (url, body, opts) => {
    if (state.portfolioId && url === '/api/transactions' && body && body.portfolio_id === undefined) body = { ...body, portfolio_id: state.portfolioId };
    if (state.portfolioId && /^\/api\/contributions\/\d+\/record$/.test(url)) url += qs({ portfolio_id: state.portfolioId });
    return request('POST', url, body ?? {}, opts);
  },
  put: (url, body, opts) => request('PUT', url, body, opts),
  patch: (url, body, opts) => request('PATCH', url, body, opts),
  del: (url, opts) => request('DELETE', url, undefined, opts),
  postRaw: (url, text, opts) => request('POST', url, text, { ...opts, raw: true }),
};
