.PHONY: validate check-prerequisites check-bash

# Point d'entree local unique pour les controles actuellement disponibles.
validate: check-prerequisites check-bash

check-prerequisites:
	@command -v bash >/dev/null || { printf '%s\n' 'Bash est requis.' >&2; exit 1; }
	@command -v docker >/dev/null || { printf '%s\n' 'Docker avec Compose est requis.' >&2; exit 1; }
	@docker compose version >/dev/null
	@command -v node >/dev/null || { printf '%s\n' 'Node.js est requis.' >&2; exit 1; }
	@command -v npm >/dev/null || { printf '%s\n' 'npm est requis.' >&2; exit 1; }
	@command -v python3 >/dev/null || { printf '%s\n' 'Python 3.12 est requis.' >&2; exit 1; }
	@python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "Python 3.12 est requis.")'
	@command -v uv >/dev/null || { printf '%s\n' 'uv est requis.' >&2; exit 1; }

check-bash:
	bash -n bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh
