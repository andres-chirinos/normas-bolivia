PYTHON := ./.venv/bin/python

.PHONY: dev dev-render dev-preview build

dev: dev-preview

dev-render:
	$(PYTHON) script/render_dev.py --limit 10

dev-preview:
	$(PYTHON) script/preview_dev.py --limit 10 --port 4200 --no-browser

build:
	quarto render
