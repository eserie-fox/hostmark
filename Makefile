.PHONY: sync format format-check lint typecheck test registry-check build check clean

sync:
	uv sync --extra dev

format:
	uv run ruff check --fix .
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src tests

test:
	uv run pytest

registry-check:
	uv run hostmark registry validate --registry registry/hosts.example.json
	@if [ -f registry/hosts.json ]; then \
		uv run hostmark registry validate --registry registry/hosts.json; \
	fi

build:
	uv build
	uvx twine check dist/*
	python scripts/verify_artifacts.py dist

check: format-check lint typecheck test registry-check

clean:
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache build dist htmlcov *.egg-info src/*.egg-info
	find src tests scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	find src tests scripts -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
