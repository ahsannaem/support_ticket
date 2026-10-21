.PHONY: test integration_tests lint format
test:
	python -m pytest tests
integration_tests:
	python -m pytest tests/integration_tests
lint:
	python -m ruff check src tests
	python -m ruff format --check src tests
format:
	python -m ruff check --fix src tests
	python -m ruff format src tests
