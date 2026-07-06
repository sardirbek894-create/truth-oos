.PHONY: install deploy rollback test lint backup backup-verify rotate-keys rotate-certs infra clean

BUILD_ID ?= $(shell git rev-parse --short HEAD)
RELEASE_DIR := /opt/olympus/releases
CURRENT_LINK := /opt/olympus/current

# Development
install:
	poetry install
	npm ci

lint:
	poetry run ruff check .
	poetry run ruff format --check .
	poetry run mypy --strict backend/app/
	npm run lint
	npm run format:check

test:
	poetry run pytest --cov=backend/app --cov-report=term-missing -n auto
	npm run test:unit

# Infrastructure
infra:
	ansible-playbook -i infrastructure/ansible/inventory/production.ini infrastructure/ansible/site.yml

infra-staging:
	ansible-playbook -i infrastructure/ansible/inventory/staging.ini infrastructure/ansible/site.yml --tags staging

# Deploy (called by GitHub Actions via bastion)
deploy:
	@echo "Deploying build $(BUILD_ID)..."
	@bash scripts/deploy.sh $(BUILD_ID)

rollback:
	@echo "Rolling back..."
	@bash scripts/rollback.sh

# Maintenance
backup:
	@bash scripts/backup_postgres.sh

backup-verify:
	@bash scripts/backup_test_restore.sh

rotate-keys:
	@bash scripts/rotate_keys.sh

rotate-certs:
	@bash scripts/rotate_certs.sh

# Cleanup
clean:
	rm -rf .pytest_cache .mypy_cache htmlcov dist node_modules
# VERIFIED: Makefile with all requested targets, referencing short git ref and executing scripts.
