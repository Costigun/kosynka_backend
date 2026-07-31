import pytest
from pydantic import ValidationError

from app.config import Settings

DSN = "postgresql+asyncpg://user:pass@host:5432/kosynka"

# Везде _env_file=None: иначе тесты читали бы .env разработчика и результат
# зависел бы от того, что у него лежит на диске. Особенно это ломало бы проверку
# «без DSN настройки не создаются» — DSN нашёлся бы в файле, и исключения не было.


def test_переменные_читаются_с_префиксом_kosynka(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
    monkeypatch.setenv("KOSYNKA_DB_POOL_SIZE", "7")

    settings = Settings(_env_file=None)

    assert settings.database_url == DSN
    assert settings.db_pool_size == 7


def test_размер_пула_имеет_дефолт(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
    monkeypatch.delenv("KOSYNKA_DB_POOL_SIZE", raising=False)

    assert Settings(_env_file=None).db_pool_size == 5


def test_без_dsn_настройки_не_создаются(monkeypatch: pytest.MonkeyPatch) -> None:
    """Дефолта у database_url нет намеренно: падение на старте честнее,
    чем работа с пустой строкой."""
    monkeypatch.delenv("KOSYNKA_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_лишние_переменные_окружения_игнорируются(monkeypatch: pytest.MonkeyPatch) -> None:
    """В контейнер прилетает больше переменных, чем нужно приложению —
    незнакомые не должны ронять старт."""
    monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
    monkeypatch.setenv("KOSYNKA_НЕИЗВЕСТНАЯ_НАСТРОЙКА", "мусор")

    assert Settings(_env_file=None).database_url == DSN
