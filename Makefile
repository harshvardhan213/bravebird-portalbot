PY ?= python3
VENV = .venv
BIN = $(VENV)/bin

.PHONY: setup run doctor test clean-state

setup:          ## one-command setup
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	$(BIN)/playwright install chromium
	@test -f .env || cp .env.example .env
	@echo "Setup done. Fill in .env, then run: make doctor"

doctor:         ## check .env and the TOTP secret
	$(BIN)/python -m portalbot doctor

run:            ## make run INPUT=inputs/main-statement.json
	$(BIN)/python -m portalbot run --input $(or $(INPUT),inputs/main-invoice.json)

test:           ## offline resolver test (no network, no account needed)
	$(BIN)/pytest -q

clean-state:    ## forget the saved session
	rm -f state/*.json
