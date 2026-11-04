# مستندات API — CapitalPilot 2.4.0

> این فایل از روی خود برنامه تولید شده است (`python tools/gen_api_docs.py`). مشخصات کامل OpenAPI در `docs/openapi.json` است.
> روی سرور production مستندات تعاملی (`/api/docs`) به‌طور پیش‌فرض خاموش است (`DOCS_ENABLED=false`).

## قراردادهای عمومی

- نشانی پایه: `https://<دامنه>/api` — همهٔ پاسخ‌ها JSON هستند و `Cache-Control: no-store` دارند.
- **احراز هویت:** اگر `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD` تنظیم شده باشد، همهٔ مسیرها (به‌جز `OPTIONS`) Basic Auth می‌خواهند: `curl -u user:pass https://<دامنه>/api/health`.
- **خطاها:** قالب یکسان `{"error": {"code": "...", "message": "پیام فارسی", "details": ...}}`. خطای ۵۰۰ فقط پیام عمومی برمی‌گرداند؛ جزئیات فنی فقط در لاگ سرور است.
- **اعتبارسنجی:** کدهای `422` (ورودی نامعتبر)، `404`، `409` (تعارض/تکراری).
- **اعداد مالی** به‌صورت رشتهٔ دهدهی دقیق (Decimal) ارسال/دریافت می‌شوند، نه float. تاریخ‌ها میلادی (ISO 8601) هستند؛ تبدیل به شمسی فقط در رابط کاربری است.
- **عملیات حساس** (`/api/backup/restore`، `/api/data/reset/*` که دو مرحله‌ای است، و `/api/search/link`، `/api/search/create-asset`، `/api/search/add-to-portfolio`) نیازمند `confirm: true` یا `?confirm=true` هستند.
- **هیچ سفارش خرید/فروش خودکاری** ساخته یا ارسال نمی‌شود؛ کلیدهای API منابع قیمت هرگز در پاسخ‌ها برنمی‌گردند (فقط `has_api_key`).

## فهرست مسیرها (120 عملیات)

### هسته: سلامت، متادیتا، تنظیمات، داشبورد  (`core`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/currencies` | — | — | 200  |
| POST | `/api/currencies` | — | `CurrencyIn` | 201  |
| DELETE | `/api/currencies/{code}` | `code`* | — | 200  |
| PUT | `/api/currencies/{code}` | `code`* | `CurrencyIn` | 200  |
| GET | `/api/health` | — | — | 200  |
| GET | `/api/meta` | — | — | 200  |
| GET | `/api/settings` | — | — | 200  |
| PUT | `/api/settings` | — | `SettingsIn` | 200  |

### کاتالوگ: ارزها، پلتفرم‌ها، دسته‌بندی‌ها  (`catalog`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/asset-types` | — | — | 200  |
| POST | `/api/asset-types` | — | `AssetTypeIn` | 201  |
| DELETE | `/api/asset-types/{key}` | `key`* | — | 200  |
| PUT | `/api/asset-types/{key}` | `key`* | `AssetTypeIn` | 200  |
| GET | `/api/platforms` | `q`, `status` | — | 200  |
| POST | `/api/platforms` | — | `PlatformIn` | 201  |
| DELETE | `/api/platforms/{pid}` | `pid`* | — | 200  |
| PUT | `/api/platforms/{pid}` | `pid`* | `PlatformIn` | 200  |
| POST | `/api/platforms/{pid}/archive` | `pid`* | — | 200  |
| POST | `/api/platforms/{pid}/restore` | `pid`* | — | 200  |

### دارایی‌ها  (`assets`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/assets` | `q`, `asset_type`, `platform_id`, `status`, `sort`, `desc`, `page`, `page_size`, `portfolio_id` | — | 200  |
| POST | `/api/assets` | — | `AssetIn` | 201  |
| PUT | `/api/assets/target-weights` | `portfolio_id` | `TargetWeightsIn` | 200  |
| DELETE | `/api/assets/{asset_id}` | `asset_id`* | — | 200  |
| GET | `/api/assets/{asset_id}` | `asset_id`*, `portfolio_id` | — | 200  |
| PUT | `/api/assets/{asset_id}` | `asset_id`* | `AssetIn` | 200  |
| POST | `/api/assets/{asset_id}/active` | `asset_id`*, `active`* | — | 200  |
| POST | `/api/assets/{asset_id}/archive` | `asset_id`* | — | 200  |
| GET | `/api/assets/{asset_id}/dependencies` | `asset_id`* | — | 200  |
| PUT | `/api/assets/{asset_id}/price-sources` | `asset_id`* | `[PriceSourceIn]` | 200  |
| POST | `/api/assets/{asset_id}/purge/confirm` | `asset_id`* | `ConfirmIn` | 200  |
| POST | `/api/assets/{asset_id}/purge/request` | `asset_id`* | — | 200  |
| POST | `/api/assets/{asset_id}/refresh-price` | `asset_id`*, `all_sources` | — | 200  |
| POST | `/api/assets/{asset_id}/restore` | `asset_id`* | — | 200  |

### سبدها و هدف‌گذاری  (`portfolios`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/portfolios` | `include_archived` | — | 200  |
| POST | `/api/portfolios` | — | `PortfolioIn` | 201  |
| DELETE | `/api/portfolios/{pid}` | `pid`* | — | 200  |
| GET | `/api/portfolios/{pid}` | `pid`* | — | 200  |
| PUT | `/api/portfolios/{pid}` | `pid`* | `PortfolioIn` | 200  |
| POST | `/api/portfolios/{pid}/archive` | `pid`* | — | 200  |
| POST | `/api/portfolios/{pid}/assets` | `pid`* | `PortfolioMemberIn` | 201  |
| DELETE | `/api/portfolios/{pid}/assets/{asset_id}` | `pid`*, `asset_id`* | — | 200  |
| POST | `/api/portfolios/{pid}/make-default` | `pid`* | — | 200  |
| POST | `/api/portfolios/{pid}/restore` | `pid`* | — | 200  |
| PUT | `/api/portfolios/{pid}/targets` | `pid`* | `PortfolioTargetsIn` | 200  |

### تراکنش‌ها (دفتر کل)  (`transactions`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/transactions` | `tx_type`, `platform_id`, `asset_id`, `date_from`, `date_to`, `q`, `limit`, `offset` | — | 200  |
| POST | `/api/transactions` | — | `TransactionIn` | 201  |
| DELETE | `/api/transactions/{tx_id}` | `tx_id`* | — | 200  |
| GET | `/api/transactions/{tx_id}` | `tx_id`* | — | 200  |
| PUT | `/api/transactions/{tx_id}` | `tx_id`* | `TransactionIn` | 200  |

### قیمت‌ها و کنترل کیفیت  (`prices`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/fx` | `currency`, `limit` | — | 200  |
| POST | `/api/fx` | — | `FxIn` | 201  |
| DELETE | `/api/fx/{fx_id}` | `fx_id`* | — | 200  |
| POST | `/api/fx/{fx_id}/approve` | `fx_id`*, `approved` | — | 200  |
| GET | `/api/prices` | `asset_id`, `approved`, `provider_id`, `valid`, `limit` | — | 200  |
| POST | `/api/prices` | — | `PriceIn` | 201  |
| GET | `/api/prices/current` | — | — | 200  |
| POST | `/api/prices/fetch` | `asset_id` | — | 200  |
| DELETE | `/api/prices/{price_id}` | `price_id`* | — | 200  |
| PUT | `/api/prices/{price_id}` | `price_id`* | `PriceIn` | 200  |
| POST | `/api/prices/{price_id}/approve` | `price_id`*, `approved` | — | 200  |

### منابع قیمت، زمان‌بند و دریافت خودکار  (`market-data`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/market-data/history` | `asset_id`*, `days`, `valid_only` | — | 200  |
| POST | `/api/market-data/history/import` | — | `HistoryImportIn` | 200  |
| GET | `/api/market-data/intelligence/alerts` | `severity`, `type` | — | 200  |
| GET | `/api/market-data/intelligence/assets` | `q`, `status`, `provider_id`, `asset_id`, `include_inactive` | — | 200  |
| GET | `/api/market-data/intelligence/logs` | `date_from`, `date_to`, `provider_id`, `asset_id`, `status`, `only_errors`, `page`, `page_size` | — | 200  |
| GET | `/api/market-data/intelligence/overview` | `days`, `date_from`, `date_to` | — | 200  |
| GET | `/api/market-data/intelligence/performance` | `days`, `provider_id`, `asset_id`, `date_from`, `date_to` | — | 200  |
| GET | `/api/market-data/kinds` | — | — | 200  |
| GET | `/api/market-data/logs` | `provider_id`, `asset_id`, `only_errors`, `limit` | — | 200  |
| GET | `/api/market-data/providers` | `include_archived` | — | 200  |
| POST | `/api/market-data/providers` | — | `ProviderIn` | 201  |
| DELETE | `/api/market-data/providers/{pid}` | `pid`* | — | 200  |
| GET | `/api/market-data/providers/{pid}` | `pid`* | — | 200  |
| PUT | `/api/market-data/providers/{pid}` | `pid`* | `ProviderIn` | 200  |
| POST | `/api/market-data/providers/{pid}/archive` | `pid`* | — | 200  |
| POST | `/api/market-data/providers/{pid}/enable` | `pid`*, `enabled` | — | 200  |
| GET | `/api/market-data/providers/{pid}/history` | `pid`*, `external_id`*, `days` | — | 200  |
| GET | `/api/market-data/providers/{pid}/logs` | `pid`*, `only_errors`, `limit` | — | 200  |
| POST | `/api/market-data/providers/{pid}/purge/confirm` | `pid`* | `ConfirmIn` | 200  |
| POST | `/api/market-data/providers/{pid}/purge/request` | `pid`* | — | 200  |
| POST | `/api/market-data/providers/{pid}/restore` | `pid`* | — | 200  |
| GET | `/api/market-data/providers/{pid}/search` | `pid`*, `q` | — | 200  |
| POST | `/api/market-data/providers/{pid}/test` | `pid`* | — | 200  |
| POST | `/api/market-data/refresh` | — | — | 200  |
| GET | `/api/market-data/scheduler` | — | — | 200  |
| PUT | `/api/market-data/scheduler` | — | `SchedulerSettingsIn` | 200  |
| POST | `/api/market-data/scheduler/run` | — | — | 200  |
| GET | `/api/market-data/status` | `portfolio_id` | — | 200  |

### Iran Market Data (قیمت طلا، ارز، کریپتو و سهام ایران)  (`iran-market`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| DELETE | `/api/iran-market/link` | `asset_id`* | — | 200  |
| POST | `/api/iran-market/link` | — | `app__routers__iranmarket__LinkIn` | 200  |
| GET | `/api/iran-market/links` | `asset_id`* | — | 200  |
| GET | `/api/iran-market/overview` | — | — | 200  |
| POST | `/api/iran-market/refresh` | — | — | 200  |
| GET | `/api/iran-market/snapshots` | `limit` | — | 200  |
| GET | `/api/iran-market/snapshots/{sid}/raw` | `sid`* | — | 200  |
| GET | `/api/iran-market/suggest` | `asset_id`*, `limit` | — | 200  |
| GET | `/api/iran-market/symbols` | `q`, `category`, `market`, `currency`, `status`, `linked`, `sort`, `order`, `page`, `page_size` | — | 200  |
| GET | `/api/iran-market/symbols/{symbol}` | `symbol`* | — | 200  |
| GET | `/api/iran-market/symbols/{symbol}/history` | `symbol`*, `days` | — | 200  |
| GET | `/api/iran-market/symbols/{symbol}/stored-prices` | `symbol`*, `limit` | — | 200  |

### جست‌وجوی سراسری (بدون تغییر دادهٔ مالی بدون تأیید)  (`search`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/search` | `q`, `group`, `page`, `page_size`, `per_group` | — | 200  |
| POST | `/api/search/add-to-portfolio` | — | `AddToPortfolioIn` | 201  |
| POST | `/api/search/create-asset` | — | `CreateAssetIn` | 201  |
| POST | `/api/search/link` | — | `app__routers__search__LinkIn` | 200  |
| GET | `/api/search/suggestions` | — | — | 200  |

### تحلیل: عملکرد، ریسک، بازتوازن (بدون سفارش خودکار)  (`analytics`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/contributions` | `portfolio_id` | — | 200  |
| PATCH | `/api/contributions/{seq}` | `seq`*, `portfolio_id` | `PlanPeriodPatch` | 200  |
| POST | `/api/contributions/{seq}/record` | `seq`*, `portfolio_id` | `ContributionRecordIn` | 201  |
| GET | `/api/dashboard` | `portfolio_id` | — | 200  |
| GET | `/api/portfolio` | `portfolio_id` | — | 200  |
| GET | `/api/rebalance` | `amount`, `source`, `portfolio_id` | — | 200  |
| GET | `/api/risk` | `portfolio_id` | — | 200  |

### گزارش‌ها (PDF / Excel / CSV)  (`reports`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| GET | `/api/reports` | — | — | 200  |
| GET | `/api/reports/{key}` | `key`*, `date`, `year`, `month`, `quarter`, `date_from`, `date_to`, `portfolio_id` | — | 200  |
| GET | `/api/reports/{key}/export` | `key`*, `format`, `date`, `year`, `month`, `quarter`, `date_from`, `date_to`, `portfolio_id` | — | 200  |

### پشتیبان‌گیری، بازیابی و بازنشانی  (`data`)

| متد | مسیر | پارامترها | بدنه | پاسخ |
|---|---|---|---|---|
| POST | `/api/backup/db` | — | — | 200  |
| GET | `/api/backup/export` | — | — | 200  |
| GET | `/api/backup/list` | — | — | 200  |
| POST | `/api/backup/restore` | `confirm` | — | 200  |
| POST | `/api/data/reset/confirm` | — | `ResetConfirmIn` | 200  |
| POST | `/api/data/reset/request` | — | `ResetRequestIn` | 200  |

(* = اجباری)

## مثال‌ها

```bash
curl -s https://<دامنه>/api/health
curl -s -u USER:PASS https://<دامنه>/api/search?q=طلا
curl -s -u USER:PASS -X POST https://<دامنه>/api/backup/db
```
