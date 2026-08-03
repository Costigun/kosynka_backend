import pytest
from pydantic import ValidationError

from app.config import Settings

DSN = "postgresql+asyncpg://user:pass@host:5432/kosynka"

# Везде _env_file=None: иначе тесты читали бы .env разработчика и результат
# зависел бы от того, что у него лежит на диске. Особенно это ломало бы проверку
# «без DSN настройки не создаются» — DSN нашёлся бы в файле, и исключения не было.


class TestSettings:
    """Чтение настроек из окружения."""

    def test_env_vars_read_with_kosynka_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
        monkeypatch.setenv("KOSYNKA_DB_POOL_SIZE", "7")

        settings = Settings(_env_file=None)

        assert settings.database_url == DSN
        assert settings.db_pool_size == 7

    def test_pool_size_has_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
        monkeypatch.delenv("KOSYNKA_DB_POOL_SIZE", raising=False)

        assert Settings(_env_file=None).db_pool_size == 5

    def test_settings_fail_without_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Дефолта у database_url нет намеренно: падение на старте честнее,
        чем работа с пустой строкой."""
        monkeypatch.delenv("KOSYNKA_DATABASE_URL", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_unknown_env_vars_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """В контейнер прилетает больше переменных, чем нужно приложению —
        незнакомые не должны ронять старт."""
        monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
        monkeypatch.setenv("KOSYNKA_SOME_UNKNOWN_SETTING", "junk")

        assert Settings(_env_file=None).database_url == DSN


class TestXpCurveSettings:
    """Параметры кривой опыта."""

    def test_defaults_match_xp_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пустое окружение не должно ломать кривую: дефолты Settings обязаны
        совпадать с дефолтами XpConfig, иначе поведение разойдётся."""
        monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
        for name in ("BASE", "TARGET_SECONDS", "K_MIN", "K_MAX", "LEVEL_BASE", "LEVEL_GROWTH"):
            monkeypatch.delenv(f"KOSYNKA_XP_{name}", raising=False)

        settings = Settings(_env_file=None)

        assert (settings.xp_base, settings.xp_target_seconds) == (100, 300)
        assert (settings.xp_k_min, settings.xp_k_max) == (0.5, 2.0)
        assert (settings.xp_level_base, settings.xp_level_growth) == (200, 1.25)

    def test_curve_params_read_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Перебалансировка кривой — правка переменных, а не пересборка образа."""
        monkeypatch.setenv("KOSYNKA_DATABASE_URL", DSN)
        monkeypatch.setenv("KOSYNKA_XP_BASE", "250")
        monkeypatch.setenv("KOSYNKA_XP_K_MAX", "3.0")

        settings = Settings(_env_file=None)

        assert settings.xp_base == 250
        assert settings.xp_k_max == 3.0
