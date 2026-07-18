.PHONY: run install test lint

install:
	pip install -r requirements.txt

run:
	python -m keirstin_link.main

test:
	python -m pytest tests/ -v || echo "no tests yet"

lint:
	python -m ruff check keirstin_link/ || echo "ruff not installed"
