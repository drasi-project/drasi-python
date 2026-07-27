# Copyright 2026 The Drasi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

PYTHON_VERSION ?= 3.12
VENV := .venv
PY := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
MATURIN := VIRTUAL_ENV="$(CURDIR)/$(VENV)" $(VENV)/bin/maturin

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: venv
venv: ## Create the development virtualenv
	uv venv --python $(PYTHON_VERSION) $(VENV)
	uv pip install --python $(PY) maturin pytest pytest-asyncio pytest-timeout ruff pyright

.PHONY: develop
develop: ## Build the extension and install it editable
	$(MATURIN) develop

.PHONY: develop-release
develop-release: ## Build optimised, with the RocksDB index backend
	$(MATURIN) develop --release --features rocksdb

.PHONY: plugins
plugins: ## Build the cdylib test plugins from crates.io
	$(PY) scripts/build_plugins.py

.PHONY: examples
examples: ## Run the examples that need no Docker
	$(PY) examples/python_source.py
	$(PY) examples/install_plugin.py

# A prerequisite rather than something you run directly, so it is not listed in
# `make help`. Without these packages the Docker-backed tests skip themselves
# and look like they passed.
.PHONY: docker-extras
docker-extras:
	uv pip install --python $(PY) "testcontainers>=4.15" "psycopg[binary]"

.PHONY: example-postgres
example-postgres: docker-extras ## Run the Postgres example (needs Docker)
	$(PY) examples/postgres_cdc.py

.PHONY: test
test: ## Run unit tests and tier 1 (hermetic) end-to-end tests
	$(PYTEST) -m "not plugins and not oci and not docker"

.PHONY: test-plugins
test-plugins: plugins ## Tier 2a: locally built cdylib plugins
	$(PYTEST) -m plugins

.PHONY: test-oci
test-oci: ## Tier 2b/2c: download and install plugins from ghcr.io
	DRASI_OCI_TESTS=1 $(PYTEST) -m oci

.PHONY: test-docker
test-docker: docker-extras ## Tier 3: real backing services via testcontainers
	DRASI_OCI_TESTS=1 $(PYTEST) -m docker

.PHONY: test-all
test-all: plugins docker-extras ## Every tier
	DRASI_OCI_TESTS=1 $(PYTEST)

.PHONY: lint
lint: ## Lint Rust and Python
	cargo clippy --all-targets -- -D warnings
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

.PHONY: fmt
fmt: ## Format Rust and Python
	cargo fmt
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

.PHONY: typecheck
typecheck: ## Strict type-check the Python facade
	$(VENV)/bin/pyright

.PHONY: check-pins
check-pins: ## Verify our crate pins still match the published plugin registry
	$(PY) scripts/check_registry_pins.py

.PHONY: clean
clean: ## Remove build artefacts
	cargo clean
	rm -rf plugins .plugin-cache .pytest_cache .ruff_cache
	find python -name '*.so' -delete
