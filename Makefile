.PHONY: up down reset test migrate lint check-ac build-all

GIT_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")

up:
	docker compose -f deploy/compose/docker-compose.yml up -d

down:
	docker compose -f deploy/compose/docker-compose.yml down

reset:
	docker compose -f deploy/compose/docker-compose.yml down -v

test:
	@if [ -n "$(SERVICE)" ]; then \
		pytest libs/platform_contracts tools/tests/ services/$(SERVICE)/tests; \
	else \
		pytest libs/platform_contracts tools/tests/ services/*/tests; \
	fi

migrate:
	@if [ -z "$(SERVICE)" ]; then echo "Usage: make migrate SERVICE=<name>"; exit 1; fi
	alembic -c services/$(SERVICE)/alembic.ini upgrade head

lint:
	ruff check .
	mypy libs/platform_contracts tools/

check-ac:
	python tools/check_ac_coverage.py

build-all:
	@for svc in $$(ls services); do \
		if [ -d "services/$$svc" ]; then \
			echo "Building $$svc with tag $(GIT_SHA)..."; \
			docker build -f services/$$svc/Dockerfile -t karobarone-$$svc:$(GIT_SHA) -t karobarone-$$svc:latest .; \
		fi \
	done
