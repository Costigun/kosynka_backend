from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения.

    Все переменные окружения читаются с префиксом ``KOSYNKA_``: поле
    ``database_url`` берётся из ``KOSYNKA_DATABASE_URL``. Лишние переменные
    в окружении игнорируются — в контейнер их приходит больше, чем нужно.
    """

    # env_file нужен только для локальной разработки: он позволяет не держать
    # переменные в окружении оболочки и не настраивать их отдельно в IDE.
    # На сервере файла нет, и это не ошибка — там всё приходит из .env.app
    # через docker compose. Настоящее окружение всегда важнее файла.
    model_config = SettingsConfigDict(env_prefix="KOSYNKA_", env_file=".env", extra="ignore")

    # Обязательная, дефолта нет намеренно: приложение без базы бессмысленно,
    # и падение на старте честнее, чем работа с пустой строкой.
    # Драйвер именно postgresql+asyncpg, а параметр TLS называется ssl, не sslmode.
    database_url: str

    # Размер пула соединений на один процесс. Умноженный на число контейнеров,
    # он не должен упираться в max_connections managed-инстанса.
    db_pool_size: int = 5


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за процесс."""
    # mypy синтезирует __init__ из объявленных полей и считает database_url
    # обязательным аргументом. На деле его подставляет pydantic-settings
    # из переменной KOSYNKA_DATABASE_URL — передавать здесь нечего.
    return Settings()  # type: ignore[call-arg]
