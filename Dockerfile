# Сборка зависимостей отдельным слоем: pyproject.toml и poetry.lock копируются
# до исходников, поэтому правка кода не пересобирает venv.
FROM python:3.12-slim AS builder

ENV POETRY_VERSION=2.4.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/tmp/poetry-cache \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /app
COPY pyproject.toml poetry.lock ./

# --only main: dev-группа (ruff, mypy, pytest) в образ не попадает.
# --no-root: сам пакет приложения ставится копированием исходников ниже.
RUN poetry install --only main --no-root && rm -rf "${POETRY_CACHE_DIR}"


FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Непривилегированный пользователь: контейнер ничего не пишет в файловую систему,
# кроме /tmp, поэтому root не нужен.
RUN useradd --create-home --uid 10001 kosynka && chown -R kosynka:kosynka /app
USER kosynka

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
