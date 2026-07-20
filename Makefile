.PHONY: validate check-prerequisites check-bash check-shellcheck check-shfmt \
	test-bash test-validators test-dry-run test-install-cli test-app-configure-local-only test-routes-dns-lifecycle test-app-install-rollback \
	test-compose-matrix check-release check-compose test-docker check-webui

# Controle par defaut: aucun acces reseau ni daemon Docker n'est necessaire.
validate: check-prerequisites check-bash check-shellcheck check-shfmt test-bash test-compose-matrix

check-prerequisites:
	@command -v bash >/dev/null || { printf '%s\n' 'Bash est requis.' >&2; exit 1; }

check-bash:
	bash -n bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh

# Linters are useful locally but must not make the offline baseline unavailable.
check-shellcheck:
	@if command -v shellcheck >/dev/null; then \
		shellcheck bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh tests/bash/*.sh tests/docker/*.sh; \
	else \
		printf '%s\n' 'SKIP: ShellCheck absent. Installez-le avec: sudo apt-get install shellcheck'; \
	fi

check-shfmt:
	@if command -v shfmt >/dev/null; then \
		shfmt -d bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh tests/bash/*.sh tests/docker/*.sh; \
	else \
		printf '%s\n' 'SKIP: shfmt absent. Installez-le depuis https://github.com/mvdan/sh/releases'; \
	fi

test-bash: test-validators test-dry-run test-install-cli test-app-configure-local-only test-routes-dns-lifecycle test-app-install-rollback

test-validators:
	bash tests/bash/test_validators.sh

test-dry-run:
	bash tests/bash/test_dry_run.sh

test-install-cli:
	bash tests/bash/test_install_cli.sh

test-app-configure-local-only:
	bash tests/bash/test_app_configure_local_only.sh

test-routes-dns-lifecycle:
	bash tests/bash/test_routes_dns_lifecycle.sh

test-app-install-rollback:
	bash tests/bash/test_app_install_rollback.sh

test-compose-matrix:
	bash tests/bash/test_compose_matrix.sh

check-release: validate
	bash tests/bash/check_release.sh

# Controles opt-in: ils peuvent exiger Docker ou les dependances du Web UI.
check-compose:
	@command -v docker >/dev/null || { printf '%s\n' 'Docker avec Compose est requis.' >&2; exit 1; }
	@docker compose version >/dev/null
	bash tests/bash/test_compose_matrix.sh --docker
	bash tests/bash/test_wordpress_template.sh

test-docker:
	bash tests/docker/test_integration.sh
	bash tests/bash/test_compose_templates.sh

check-webui:
	$(MAKE) -C templates/apps/webui verify
