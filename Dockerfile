FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_INDEX_URL=https://pypi.org/simple

RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --default-index "${UV_INDEX_URL}"

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY docker ./docker

ENV PATH="/app/.venv/bin:${PATH}" \
    CCNR_DATA_BIND=0.0.0.0:8081 \
    CCNR_DATA_DB_FILE=/data/ccnr-data.db

EXPOSE 8081 8082

ENTRYPOINT ["./docker/entrypoint.sh"]
