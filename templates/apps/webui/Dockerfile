FROM node:20.19.2-bookworm-slim AS assets

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY src/ ./src/
RUN npm run assets:vendor && npm run css:build

FROM ghcr.io/astral-sh/uv:0.7.13-python3.12-bookworm-slim AS python-builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12.11-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl jq \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && printf '%s\n' \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
      > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       docker-ce-cli=5:28.3.3-1~debian.12~bookworm \
       docker-compose-plugin=2.38.2-1~debian.12~bookworm \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1

COPY src/ .
COPY ksf/ /app/ksf/
COPY --from=assets /app/src/webui/static/app.css /app/webui/static/app.css

EXPOSE 8000
CMD ["uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "8000"]
