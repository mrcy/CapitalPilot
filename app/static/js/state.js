// وضعیت سراسری برنامه (متادیتا، تنظیمات و سبد انتخاب‌شده)
import { api } from './api.js';
import { setAssetTypes } from './format.js';

export const state = { meta: null, settings: null, portfolioId: null };
const KEY = 'cp.portfolio';

export async function refreshMeta() {
  state.meta = await api.get('/api/meta', { portfolio_id: state.portfolioId || undefined });
  state.settings = state.meta.settings;
  setAssetTypes(state.meta.asset_types);
  const saved = Number(localStorage.getItem(KEY));
  const live = state.meta.portfolios.filter((p) => !p.is_archived);
  const pick = live.find((p) => p.id === (state.portfolioId || saved)) || live.find((p) => p.is_default) || live[0];
  state.portfolioId = pick?.id || null;
  return state.meta;
}
export function setPortfolio(id) { state.portfolioId = id; localStorage.setItem(KEY, String(id)); }
export const calendar = () => state.settings?.calendar || 'jalali';
export const unitLabel = () => state.settings?.currency_label || 'تومان';
export const platformName = (id) => state.meta?.platforms.find((p) => p.id === id)?.name || '';
export const currentPortfolio = () => state.meta?.portfolios.find((p) => p.id === state.portfolioId);
export const typeInfo = (key) => state.meta?.asset_types.find((t) => t.key === key);
