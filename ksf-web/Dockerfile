FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      bash \
      curl \
      docker.io \
      gosu \
      tini && \
    rm -rf /var/lib/apt/lists/*

# Ajoute le binaire `docker` CLI + plugin `docker compose` (manquants dans
# `docker.io` sur Debian 12, qui ne fournit que dockerd). Nécessaires pour
# que `app.sh <action> <app>` puisse appeler `docker compose` sur la stack
# de l'app. Binaires statiques depuis download.docker.com / GitHub releases,
# compatibles avec toutes les architectures.
ARG DOCKER_CLI_VERSION=27.3.1
ARG DOCKER_COMPOSE_VERSION=2.32.4
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64) compose_arch='x86_64' ;; \
      aarch64|arm64) compose_arch='aarch64' ;; \
      *) echo "Architecture non supportée: $arch" >&2; exit 1 ;; \
    esac; \
    case "$arch" in \
      x86_64) docker_arch='x86_64' ;; \
      aarch64|arm64) docker_arch='aarch64' ;; \
      *) echo "Architecture non supportée: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_CLI_VERSION}.tgz" \
      | tar xz -C /tmp; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker; \
    mkdir -p /usr/local/libexec/docker/cli-plugins; \
    curl -fsSLo /usr/local/libexec/docker/cli-plugins/docker-compose \
      "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${compose_arch}"; \
    chmod 0755 /usr/local/libexec/docker/cli-plugins/docker-compose; \
    mkdir -p /root/.docker/cli-plugins; \
    ln -sf /usr/local/libexec/docker/cli-plugins/docker-compose /root/.docker/cli-plugins/docker-compose; \
    docker --version; \
    docker compose version

RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m -s /bin/bash appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN chown -R appuser:appuser /app

# L'entrypoint s'exécute en root pour valider les perms du bind mount,
# puis drop privs via gosu. Le bind mount (${BASE_DIR}/.ksf-web-data)
# est créé et chowné côté host par app_install.
USER root

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8400"]
