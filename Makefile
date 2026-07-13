# Shortcuts around the docker compose file combinations.
# Run `make` (or `make help`) to list targets.

COMPOSE ?= docker compose
BASE    := -f docker-compose.yml
BUILD   := $(BASE) -f docker-compose.build.yml
DEV     := $(BASE) -f docker-compose.dev.yml
TS      := -f docker-compose.tailscale.yml
DEV_TS  := $(TS) -f docker-compose.dev.yml

.DEFAULT_GOAL := help
.PHONY: help up pull update build dev dev-tailscale tailscale down logs ps release

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Run the published image (pull) in the background
	$(COMPOSE) $(BASE) up -d

pull: ## Pull the latest published image
	$(COMPOSE) $(BASE) pull

update: pull ## Pull the latest image and restart
	$(COMPOSE) $(BASE) up -d

build: ## Build the image from local source and run
	$(COMPOSE) $(BUILD) up -d --build

dev: ## Live-reload dev server (foreground; Ctrl+C to stop)
	$(COMPOSE) $(DEV) up

dev-tailscale: ## Live-reload dev server as a node on your tailnet
	$(COMPOSE) $(DEV_TS) up

tailscale: ## Run the published image as a tailnet node (background)
	$(COMPOSE) $(TS) up -d

down: ## Stop & remove everything, any mode (incl. the tailscale sidecar)
	$(COMPOSE) $(BASE) down --remove-orphans

logs: ## Follow container logs
	$(COMPOSE) $(BASE) logs -f

ps: ## Show running containers
	$(COMPOSE) $(BASE) ps

release: ## Tag & push a release:  make release VERSION=v1.0.0
	@test -n "$(VERSION)" || { echo "Usage: make release VERSION=vX.Y.Z"; exit 1; }
	git tag $(VERSION)
	git push origin $(VERSION)
	@echo "Pushed $(VERSION) — CI will publish ghcr.io/reneabreu/yamtrack-importer:$(VERSION:v%=%)"
