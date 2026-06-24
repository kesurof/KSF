FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      bash \
      curl \
      docker.io \
      gosu \
      tini && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m -s /bin/bash appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN chown -R appuser:appuser /app

# L'entrypoint s'exécute en root pour chown le volume DB, puis drop privs via gosu.
# C'est nécessaire car les volumes Docker nommés sont root:root 755 par défaut.
USER root

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8400"]
