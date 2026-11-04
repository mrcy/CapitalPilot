import { api } from '../api.js';
import { reloadAll } from '../app.js';
import { badge, clear, confirmDialog, formModal, h, icon, notice, pageHead, table, toast } from '../ui.js';
import { num } from '../format.js';
import { pager, toolbar } from '../listkit.js';

export const PLATFORM_KINDS = { funds: 'صندوق‌ها', digital: 'رمزارز', exchange: 'بورس', commodity: 'بورس کالا', broker: 'کارگزاری', foreign: 'بازار خارجی', personal: 'شخصی', other: 'سایر' };

export function openPlatformForm({ platform = null, onDone } = {}) {
  return formModal({
    title: platform ? `ویرایش پلتفرم «${platform.name}»` : 'پلتفرم جدید',
    fields: [
      { name: 'name', label: 'نام پلتفرم', type: 'text', required: true },
      { name: 'kind', label: 'نوع پلتفرم', type: 'select', options: Object.entries(PLATFORM_KINDS).map(([value, label]) => ({ value, label })) },
      { name: 'sort_order', label: 'ترتیب نمایش', type: 'int' },
      { name: 'is_active', label: 'فعال', type: 'checkbox' },
      { name: 'note', label: 'توضیحات', type: 'textarea', wide: true },
    ],
    values: platform ? { ...platform } : { kind: 'other', is_active: true, sort_order: 100 },
    onSubmit: async (x, m) => {
      const body = { name: x.name.trim(), kind: x.kind, is_active: x.is_active, note: x.note || '', sort_order: x.sort_order ?? 0 };
      if (platform) await api.put(`/api/platforms/${platform.id}`, body); else await api.post('/api/platforms', body);
      m.close(); toast('پلتفرم ذخیره شد.', 'success'); onDone && onDone();
    },
  });
}

async function deletePlatform(p, done) {
  if (p.transaction_count || p.asset_count) {
    const why = p.transaction_count ? `${num(p.transaction_count)} تراکنش` : `${num(p.asset_count)} دارایی`;
    if (await confirmDialog({ title: 'حذف ممکن نیست', message: `«${p.name}» دارای ${why} است و حذف نمی‌شود تا تاریخچه سالم بماند. بایگانی شود؟ (دارایی‌ها و تراکنش‌ها دست‌نخورده می‌مانند.)`, confirmLabel: 'بایگانی' })) {
      await api.post(`/api/platforms/${p.id}/archive`); toast('پلتفرم بایگانی شد.', 'success'); done();
    }
    return;
  }
  if (await confirmDialog({ title: 'حذف پلتفرم', message: `«${p.name}» هیچ دارایی و تراکنشی ندارد و برای همیشه حذف می‌شود.`, danger: true, confirmLabel: 'حذف' })) {
    await api.del(`/api/platforms/${p.id}`); toast('پلتفرم حذف شد.', 'success'); done();
  }
}

const F = { q: '', status: 'live', page: 1, size: 10 };

export async function render(root) {
  root.append(pageHead('پلتفرم‌ها', 'محل نگهداری دارایی‌ها؛ هر دارایی به یک پلتفرم وصل است و یک ابزار می‌تواند روی چند پلتفرم، با موجودی مستقل، وجود داشته باشد.',
    h('button', { class: 'btn primary', onclick: () => openPlatformForm({ onDone: reloadAll }) }, icon('plus'), 'پلتفرم جدید')));
  const results = h('div');
  root.append(toolbar({ placeholder: 'جستجوی نام پلتفرم…', q: F.q, filters: [
    { name: 'status', label: 'وضعیت', value: F.status, options: [['live', 'فعال و غیرفعال'], ['active', 'فقط فعال'], ['archived', 'بایگانی‌شده'], ['all', 'همه']].map(([value, label]) => ({ value, label })) }],
  onChange: (v) => { Object.assign(F, v, { page: 1 }); draw(); } }), results);
  let all = await api.get('/api/platforms');
  const draw = async () => {
    const q = F.q.toLowerCase();
    let rows = all.filter((p) => (!q || p.name.toLowerCase().includes(q) || (p.note || '').toLowerCase().includes(q))
      && (F.status === 'all' || (F.status === 'archived' ? p.is_archived : F.status === 'active' ? p.is_active && !p.is_archived : !p.is_archived)));
    const total = rows.length;
    rows = rows.slice((F.page - 1) * F.size, F.page * F.size);
    clear(results);
    const done = async () => { all = await api.get('/api/platforms'); await reloadAll(); };
    results.append(h('div', { class: 'card' }, table([
      { label: 'پلتفرم', render: (p) => h('div', null, h('b', null, p.name), h('div', { class: 'muted', style: { fontSize: '12px' } }, p.note || '')) },
      { label: 'نوع', render: (p) => PLATFORM_KINDS[p.kind] || p.kind },
      { label: 'دارایی‌ها', class: 'num', render: (p) => `${num(p.active_asset_count)} فعال از ${num(p.asset_count)}` },
      { label: 'تراکنش‌ها', class: 'num', render: (p) => num(p.transaction_count) },
      { label: 'وضعیت', render: (p) => (p.is_archived ? badge('بایگانی‌شده') : p.is_active ? badge('فعال', 'ok') : badge('غیرفعال', 'warn')) },
      { label: '', render: (p) => h('div', { class: 'row-actions' },
                h('button', { class: 'icon-btn', title: 'ویرایش', 'aria-label': `ویرایش ${p.name}`, onclick: () => openPlatformForm({ platform: p, onDone: done }) }, icon('edit', 17)),
        p.is_archived
          ? h('button', { class: 'icon-btn', title: 'بازیابی', 'aria-label': `بازیابی ${p.name}`, onclick: async () => { await api.post(`/api/platforms/${p.id}/restore`); toast('بازیابی شد.', 'success'); done(); } }, icon('restore', 17))
          : h('button', { class: 'icon-btn', title: 'بایگانی', 'aria-label': `بایگانی ${p.name}`, onclick: async () => { if (await confirmDialog({ message: `«${p.name}» بایگانی شود؟ دارایی‌ها و تراکنش‌های آن حفظ می‌شود ولی برای دارایی جدید قابل انتخاب نیست.`, confirmLabel: 'بایگانی' })) { await api.post(`/api/platforms/${p.id}/archive`); toast('بایگانی شد.', 'success'); done(); } } }, icon('archive', 17)),
        h('button', { class: 'icon-btn', title: 'حذف', 'aria-label': `حذف ${p.name}`, onclick: () => deletePlatform(p, done) }, icon('trash', 17))) },
    ], rows, { empty: 'پلتفرمی پیدا نشد.', rowClass: (p) => (p.is_archived ? 'inactive' : '') })), pager({ page: F.page, pageSize: F.size, total, onPage: (p) => { F.page = p; draw(); } }));
  };
  await draw();
}
