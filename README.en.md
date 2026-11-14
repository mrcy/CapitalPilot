# CapitalPilot

**A self-hosted, Persian-first portfolio and investment tracker with RTL support and configurable market-data integrations.**

[فارسی](README.md) · [Installation (Ubuntu 24.04)](docs/INSTALL-UBUNTU-24.04.md) · [API documentation](docs/API.md) · [Security notes](docs/SECURITY.md)

> CapitalPilot is a portfolio-tracking and analysis tool. It does **not** place buy or sell orders and is **not** financial advice. All investment decisions remain with the user.

## Why CapitalPilot?

Many portfolio tools are designed around English-language interfaces and a limited set of markets. CapitalPilot is built Persian-first, supports right-to-left layouts, and provides an extensible data model for Iranian and international assets. It is self-hosted so users retain control of their financial records and deployment.

## Highlights

- **Multiple portfolios and strategies:** independent holdings, targets, contribution plans, risk limits, and performance calculations.
- **Flexible asset catalogue:** funds, stocks, crypto, gold, silver, currencies, commodities, indices, and user-defined asset types.
- **Transaction ledger:** deposits, withdrawals, buys, sells, fees, weighted-average cost basis, and realized/unrealized P&L.
- **Financial calculations:** backend calculations use Python `Decimal`; performance metrics include time-weighted return (TWR) and XIRR.
- **Market-data adapters:** TSETMC, Bitpin, configurable JSON APIs, optional provider adapters, and manual prices.
- **Price-quality safeguards:** stale, future-dated, zero, negative, or inconsistent prices are flagged and excluded from valuation when invalid. Provider fallback and discrepancy checks are supported.
- **Iran market catalogue:** import and search instruments from a configurable market-data file, then explicitly link symbols to portfolio assets.
- **Global market search:** Persian/English names, symbols, normalization of Persian and Arabic characters, synonyms, and typo-tolerant matching.
- **Risk and reporting:** drawdown monitoring, buy-allocation suggestions, and Excel/CSV/PDF reports.
- **Self-hosted operations:** Docker, Ubuntu/systemd/Nginx deployment scripts, database migrations, backup/restore, and API documentation.

## Current status

- **Current documented version:** 2.4.0
- **Default deployment target:** Ubuntu 24.04, Python 3.12, systemd, and Nginx; Docker is also supported.
- **Database:** SQLite by default; PostgreSQL is supported.
- **Architecture:** FastAPI backend and a modular browser frontend.
- **Tests:** Python unit/API tests plus optional browser-based frontend tests. See [Testing](#testing).

### Market-data verification

The project documents adapters for Iranian providers, but live connectivity to TSETMC, Bitpin, and other external services has **not** been verified from the development environment. Provider tests use mocked HTTP transport and stored fixtures. Network access, provider policies, and regional restrictions may affect real deployments. Use the in-app connection test in your own environment before relying on a provider.

## Quick start

Requirements: Python 3.11 or newer (Python 3.12+ recommended).

### Linux, Ubuntu, or macOS

```bash
./run.sh
```

The application starts at `http://127.0.0.1:8000`.

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\uvicorn app.main:app --port 8000
```

### Docker

```bash
docker compose up -d --build
```

The Docker Compose setup stores application data in the `capitalpilot-data` volume. See [Docker documentation](docs/DOCKER.md).

## Production deployment

For a production-oriented installation on Ubuntu 24.04, follow the dedicated [Ubuntu installation guide](docs/INSTALL-UBUNTU-24.04.md).

The documented production setup uses:

- Python 3.12 and a virtual environment
- A dedicated system user and systemd service
- SQLite by default, with data stored outside the web root
- Nginx as a reverse proxy and Let's Encrypt for HTTPS
- Backup timers and explicit backup/restore scripts

Do not expose the application directly to the public internet without authentication and HTTPS. Review [Security](docs/SECURITY.md) before deployment.

## Testing

Install development dependencies and run the Python test suite:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Optional frontend/browser tests require Node.js and a compatible Chrome/Chromium installation. See the test notes in [the Persian README](README.md#آزمونها) and the frontend test directory.

## Documentation

- [Ubuntu 24.04 installation](docs/INSTALL-UBUNTU-24.04.md)
- [Nginx and HTTPS](docs/NGINX-HTTPS.md)
- [Backup and restore](docs/BACKUP-RESTORE.md)
- [Market-data providers](docs/PRICE-SOURCES.md)
- [Docker](docs/DOCKER.md)
- [Security](docs/SECURITY.md)
- [API reference](docs/API.md)

## Data, privacy, and safety

- Financial records are stored by the self-hosted instance.
- API credentials for supported market-data providers are handled server-side; configured provider secrets are encrypted and are not returned to the browser.
- Backups may contain sensitive financial information. Store them securely and restrict filesystem permissions.
- Price feeds can be delayed, unavailable, or incorrect. Review source, timestamp, currency, and quality status before using any displayed value.
- Allocation suggestions are calculations based on configured targets and available data, not personalized financial advice.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or proposing a change.

## License

CapitalPilot is distributed under the [MIT License](LICENSE). You may use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software, subject to the conditions in the license text. The software is provided "as is", without warranty.
