SHELL := /bin/bash
export VIDEO
.PHONY: setup install start stop status dev test lint build taxa benchmark
setup:
	bash scripts/bootstrap.sh
install:
	bash scripts/install.sh
start:
	bash scripts/serve.sh start
stop:
	bash scripts/serve.sh stop
status:
	bash scripts/serve.sh status
dev:
	bash scripts/dev.sh
test:
	bash -c 'source scripts/env.sh && cd backend && pytest -q'
	bash -c 'source scripts/env.sh && pytest -q scripts/test_*.py'
	bash -c 'source scripts/env.sh && cd frontend && npm test'
lint:
	bash -c 'source scripts/env.sh && cd backend && ruff check . ../scripts ../training && mypy app'
	bash -c 'source scripts/env.sh && cd frontend && npm run lint'
build:
	bash -c 'source scripts/env.sh && cd frontend && npm run build'
taxa:
	bash -c 'source scripts/env.sh && python scripts/build_rajasthan_taxa.py'
benchmark:
	@test -n "$$VIDEO" || (echo 'Usage: make benchmark VIDEO=data/samples/example.mp4'; exit 2)
	bash -c 'source scripts/env.sh && python scripts/benchmark.py "$$VIDEO"'
