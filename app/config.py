from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.xp import XpConfig


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

    # Параметры кривой опыта. Живут в окружении, а не в коде: перебалансировка
    # не должна требовать пересборки образа. Значения дублируют дефолты XpConfig —
    # держать их синхронными обязательно, иначе поведение с пустым окружением
    # и с заданным разойдётся.
    xp_base: int = 100
    xp_target_seconds: int = 300
    xp_k_min: float = 0.5
    xp_k_max: float = 2.0
    xp_level_base: int = 200
    xp_level_growth: float = 1.25


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за процесс."""
    # mypy синтезирует __init__ из объявленных полей и считает database_url
    # обязательным аргументом. На деле его подставляет pydantic-settings
    # из переменной KOSYNKA_DATABASE_URL — передавать здесь нечего.
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_xp_config() -> XpConfig:
    """Параметры кривой из окружения.

    Отдельная функция, а не поле Settings: ``app.xp`` про настройки ничего не
    знает и знать не должен, поэтому мост между ними строится здесь.
    Вызывается в lifespan — чтобы кривая с невозможными параметрами роняла
    старт приложения, а не первый пришедший запрос.
    """
    settings = get_settings()
    return XpConfig(
        base_xp=settings.xp_base,
        target_seconds=settings.xp_target_seconds,
        k_min=settings.xp_k_min,
        k_max=settings.xp_k_max,
        level_base_xp=settings.xp_level_base,
        level_growth=settings.xp_level_growth,
    )
