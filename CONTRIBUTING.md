# Contributing to CapitalPilot

Thank you for taking an interest in CapitalPilot.

## Before submitting code

**Licensing is not yet configured.** This repository currently has no `LICENSE` file. Until the maintainer adds an explicit open-source license and contribution terms, please do not submit patches that assume the project is already open source. Bug reports, reproducible test cases, documentation feedback, and feature discussions are welcome.

## Reporting a bug

Please include:

- The CapitalPilot version and deployment method (local, Docker, or systemd/Nginx).
- Python and operating-system versions.
- The exact steps to reproduce the issue.
- Expected and actual behavior.
- Relevant sanitized logs or error messages.

Never include API keys, passwords, database files, backups, personal financial records, or other secrets in an issue.

## Proposing a feature

Describe the user problem first, then the proposed behavior and any alternatives considered. For financial calculations, include a small reproducible example with expected results and specify currency, units, fees, and rounding assumptions.

## Development and tests

1. Create an isolated Python environment.
2. Install runtime and development dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
3. Run the Python suite:
   ```bash
   python -m pytest -q
   ```
4. For optional frontend/browser tests, follow the instructions in `tests/frontend` and ensure Node.js plus Chrome/Chromium are available.

Keep tests deterministic. External market-data integrations should use mocked HTTP transport or checked-in fixtures rather than depending on live provider availability.

## Design principles

- Preserve financial precision; use Python `Decimal` for monetary calculations.
- Never treat stale, invalid, or unverified market data as a valid live price.
- Do not introduce automatic trade execution. CapitalPilot is a tracking and analysis application.
- Keep secrets out of source control, logs, browser code, screenshots, and issue reports.
- Preserve Persian/RTL behavior and verify both desktop and mobile layouts for UI changes.
- Include or update tests and documentation when behavior changes.

## Pull requests

Once licensing and contribution terms are published, proposed pull requests should be focused, include a clear rationale, describe user-visible changes, and provide tests for behavior changes. Do not bundle unrelated refactors with bug fixes.
