.PHONY: assets audit-npm audit-python build check css css-watch lock-check test test-ui ui-install-browser verify

assets:
	npm run assets:vendor

css: assets
	npm run css:build

css-watch:
	npm run css:watch

check:
	uv run ruff check src

test:
	uv run pytest

ui-install-browser:
	uv run playwright install chromium

test-ui: css
	uv run pytest src/tests/ui

audit-python:
	uv run pip-audit

audit-npm:
	npm audit

lock-check:
	uv lock --check
	npm ci --ignore-scripts --dry-run

build:
	docker build --pull=false -t ksf-webui:local .

verify: lock-check check test css
