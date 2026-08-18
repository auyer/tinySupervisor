.PHONY: test test-unit test-e2e lint format format-check typecheck check

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit

test-e2e:
	uv run pytest tests/e2e

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run ty check src tests

check: test lint format-check typecheck
