FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Set by CI to the release version (e.g. 0.2.0); source builds report "dev"
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

RUN mkdir -p /data/books /data/covers

COPY migrate.sh start.sh /app/
RUN chmod +x /app/migrate.sh /app/start.sh
CMD ["/app/start.sh"]
