BEGIN TRANSACTION;
CREATE TABLE app_settings (
	id INTEGER NOT NULL, 
	initial_capital VARCHAR(64) NOT NULL, 
	monthly_contribution VARCHAR(64) NOT NULL, 
	horizon_months INTEGER NOT NULL, 
	plan_start_date DATE NOT NULL, 
	max_drawdown_pct VARCHAR(64) NOT NULL, 
	concentration_limit_pct VARCHAR(64) NOT NULL, 
	deviation_warning_pp VARCHAR(64) NOT NULL, 
	max_price_age_days INTEGER NOT NULL, 
	calendar VARCHAR(16) NOT NULL, 
	currency_label VARCHAR(16) NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "app_settings" VALUES(1,'100000000','50000000',12,'2026-11-04','25','35','5',3,'jalali','تومان','2026-11-04 12:42:04');
CREATE TABLE assets (
	id INTEGER NOT NULL, 
	platform_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	symbol VARCHAR(40) NOT NULL, 
	asset_type VARCHAR(16) NOT NULL, 
	target_weight VARCHAR(64) NOT NULL, 
	price_currency VARCHAR(16) NOT NULL, 
	buy_fee_rate VARCHAR(64) NOT NULL, 
	fractional_units BOOLEAN NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	price_provider VARCHAR(40) NOT NULL, 
	price_provider_params TEXT NOT NULL, 
	sort_order INTEGER NOT NULL, 
	note TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_asset_target_nonneg CHECK (target_weight >= 0), 
	CONSTRAINT uq_asset_platform_name UNIQUE (platform_id, name), 
	FOREIGN KEY(platform_id) REFERENCES platforms (id), 
	FOREIGN KEY(price_currency) REFERENCES currencies (code)
);
INSERT INTO "assets" VALUES(1,1,'صندوق عیار','عیار','gold','25','IRT','0',0,1,'','',0,'','2026-11-04 12:42:04');
INSERT INTO "assets" VALUES(2,1,'صندوق اطلس','اطلس','fund','25','IRT','0',0,1,'','',1,'','2026-11-04 12:42:04');
INSERT INTO "assets" VALUES(3,1,'صندوق آوند','آوند','fund','10','IRT','0',0,1,'','',2,'','2026-11-04 12:42:04');
INSERT INTO "assets" VALUES(4,2,'شاخص S&P 500','SPX','index','20','IRT','0',0,1,'','',3,'','2026-11-04 12:42:04');
INSERT INTO "assets" VALUES(5,2,'سرمایه پایدار','','digital','20','IRT','0',0,1,'','',4,'','2026-11-04 12:42:04');
CREATE TABLE currencies (
	code VARCHAR(16) NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	symbol VARCHAR(16) NOT NULL, 
	is_base BOOLEAN NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	PRIMARY KEY (code)
);
INSERT INTO "currencies" VALUES('IRT','تومان','تومان',1,1);
INSERT INTO "currencies" VALUES('USD','دلار آمریکا','$',0,1);
INSERT INTO "currencies" VALUES('USDT','تتر','USDT',0,1);
CREATE TABLE fx_rates (
	id INTEGER NOT NULL, 
	currency VARCHAR(16) NOT NULL, 
	rate VARCHAR(64) NOT NULL, 
	recorded_at DATETIME NOT NULL, 
	source VARCHAR(120) NOT NULL, 
	is_approved BOOLEAN NOT NULL, 
	note TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(currency) REFERENCES currencies (code)
);
CREATE TABLE plan_periods (
	id INTEGER NOT NULL, 
	seq INTEGER NOT NULL, 
	due_date DATE NOT NULL, 
	planned_amount VARCHAR(64) NOT NULL, 
	note TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (seq)
);
INSERT INTO "plan_periods" VALUES(1,0,'2026-11-04','100000000','');
INSERT INTO "plan_periods" VALUES(2,1,'2026-12-04','50000000','');
INSERT INTO "plan_periods" VALUES(3,2,'2027-01-03','50000000','');
INSERT INTO "plan_periods" VALUES(4,3,'2027-02-02','50000000','');
INSERT INTO "plan_periods" VALUES(5,4,'2027-03-04','50000000','');
INSERT INTO "plan_periods" VALUES(6,5,'2027-04-02','50000000','');
INSERT INTO "plan_periods" VALUES(7,6,'2027-05-03','50000000','');
INSERT INTO "plan_periods" VALUES(8,7,'2027-06-03','50000000','');
INSERT INTO "plan_periods" VALUES(9,8,'2027-07-04','50000000','');
INSERT INTO "plan_periods" VALUES(10,9,'2027-08-04','50000000','');
INSERT INTO "plan_periods" VALUES(11,10,'2027-09-04','50000000','');
INSERT INTO "plan_periods" VALUES(12,11,'2027-10-05','50000000','');
INSERT INTO "plan_periods" VALUES(13,12,'2027-11-04','50000000','');
CREATE TABLE platforms (
	id INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	note TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
INSERT INTO "platforms" VALUES(1,'مفید','funds',1,'کارگزاری مفید — صندوق‌های سرمایه‌گذاری');
INSERT INTO "platforms" VALUES(2,'بیت‌پین','digital',1,'پلتفرم بیت‌پین');
CREATE TABLE prices (
	id INTEGER NOT NULL, 
	asset_id INTEGER NOT NULL, 
	price VARCHAR(64) NOT NULL, 
	currency VARCHAR(16) NOT NULL, 
	recorded_at DATETIME NOT NULL, 
	source VARCHAR(120) NOT NULL, 
	is_approved BOOLEAN NOT NULL, 
	note TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id), 
	FOREIGN KEY(currency) REFERENCES currencies (code)
);
INSERT INTO "prices" VALUES(1,1,'20000','IRT','2026-10-02 12:00:00.000000','تراکنش #2',1,'ثبت‌شده همراه تراکنش','2026-11-04 12:42:04');
INSERT INTO "prices" VALUES(2,1,'23000','IRT','2026-11-03 12:00:00.000000','manual',1,'','2026-11-04 12:42:04');
CREATE TABLE transactions (
	id INTEGER NOT NULL, 
	tx_date DATE NOT NULL, 
	platform_id INTEGER NOT NULL, 
	asset_id INTEGER, 
	tx_type VARCHAR(16) NOT NULL, 
	quantity VARCHAR(64), 
	unit_price VARCHAR(64), 
	fee VARCHAR(64) NOT NULL, 
	total_amount VARCHAR(64) NOT NULL, 
	fx_rate VARCHAR(64), 
	plan_period_id INTEGER, 
	note TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(platform_id) REFERENCES platforms (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id), 
	FOREIGN KEY(plan_period_id) REFERENCES plan_periods (id)
);
INSERT INTO "transactions" VALUES(1,'2026-10-01',1,NULL,'deposit',NULL,NULL,'0','50000000.0000',NULL,NULL,'','2026-11-04 12:42:04','2026-11-04 12:42:04');
INSERT INTO "transactions" VALUES(2,'2026-10-02',1,1,'buy','1000','20000','50000','20050000.0000',NULL,NULL,'','2026-11-04 12:42:04','2026-11-04 12:42:04');
INSERT INTO "transactions" VALUES(3,'2026-10-20',1,1,'sell','100','22000','1000','2199000.0000',NULL,NULL,'','2026-11-04 12:42:04','2026-11-04 12:42:04');
CREATE INDEX ix_assets_platform_id ON assets (platform_id);
CREATE INDEX ix_fx_cur_time ON fx_rates (currency, recorded_at);
CREATE INDEX ix_tx_date ON transactions (tx_date);
CREATE INDEX ix_transactions_asset_id ON transactions (asset_id);
CREATE INDEX ix_transactions_platform_id ON transactions (platform_id);
CREATE INDEX ix_price_asset_time ON prices (asset_id, recorded_at);
COMMIT;
