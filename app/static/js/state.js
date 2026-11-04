// وضعیت سراسری برنامه (متادیتا و تنظیمات)
import { api } from './api.js';

export const state = { meta: null, settings: null };

export async function refreshMeta() {
  state.meta = await api.get('/api/meta');
  state.settings = state.meta.settings;
  return state.meta;
}
export const calendar = () => state.settings?.calendar || 'jalali';
export const unitLabel = () => state.settings?.currency_label || 'تومان';
export const platformName = (id) => state.meta?.platforms.find((p) => p.id === id)?.name || '';
