import pytest

from app.xp import LevelInfo, XpConfig, level_for_xp, time_coefficient, xp_for_win, xp_threshold

CONFIG = XpConfig()


class TestXpForWin:
    """Опыт за победу по длительности партии."""

    # Опорная таблица «минуты → опыт». Дополняй её, а не переписывай.
    @pytest.mark.parametrize(
        ("minutes", "expected_xp"),
        [
            (0.5, 200),  # быстрее эталона впятеро — коэффициент зажат сверху
            (1, 200),
            (2.5, 200),  # ровно на верхней границе: 300/150 = 2.0
            (3, 167),
            (5, 100),  # эталонная партия
            (7.5, 67),
            # Несущая строка: 100 × 0.625 = 62.5. Банковское округление дало бы 62.
            # Если кто-то «упростит» _round_half_up обратно на round(), красной
            # станет именно она.
            (8, 63),
            (10, 50),  # ровно на нижней границе: 300/600 = 0.5
            (20, 50),
            (60, 50),  # партия на час всё равно даёт опыт, а не ноль
        ],
    )
    def test_xp_by_duration(self, minutes: float, expected_xp: int) -> None:
        assert xp_for_win(duration_ms=int(minutes * 60_000), config=CONFIG) == expected_xp

    def test_rounding_is_half_up_not_bankers(self) -> None:
        """Отдельно и явно: round(62.5) == 62, а нам нужно 63."""
        assert round(62.5) == 62
        assert xp_for_win(duration_ms=480_000, config=CONFIG) == 63


class TestTimeCoefficient:
    """Коэффициент за скорость."""

    def test_coefficient_clamped_on_both_sides(self) -> None:
        # Сверху: мгновенная партия не даёт ×100.
        assert time_coefficient(1, CONFIG) == CONFIG.k_max
        # Снизу: сколь угодно долгая партия не обнуляет награду.
        assert time_coefficient(3_600_000, CONFIG) == CONFIG.k_min
        # Эталон посередине.
        assert time_coefficient(300_000, CONFIG) == 1.0

    def test_zero_duration_is_a_limit_not_an_error(self) -> None:
        """Чистая функция обязана быть тотальной: схема запроса такого
        не пропустит, но тестировать формулу в отрыве от API должно быть можно."""
        assert time_coefficient(0, CONFIG) == CONFIG.k_max
        assert time_coefficient(-1, CONFIG) == CONFIG.k_max


class TestLevelCurve:
    """Кривая уровней."""

    @pytest.mark.parametrize(
        ("level", "expected_threshold"),
        [(1, 0), (2, 200), (3, 450), (4, 763), (5, 1154), (10, 5161)],
    )
    def test_level_thresholds(self, level: int, expected_threshold: int) -> None:
        assert xp_threshold(level, CONFIG) == expected_threshold

    @pytest.mark.parametrize(
        ("xp_total", "expected"),
        [
            (0, LevelInfo(level=1, xp_into_level=0, xp_to_next=200)),
            (199, LevelInfo(level=1, xp_into_level=199, xp_to_next=1)),
            (200, LevelInfo(level=2, xp_into_level=0, xp_to_next=250)),
            (449, LevelInfo(level=2, xp_into_level=249, xp_to_next=1)),
            (450, LevelInfo(level=3, xp_into_level=0, xp_to_next=313)),
            (5161, LevelInfo(level=10, xp_into_level=0, xp_to_next=1490)),
        ],
    )
    def test_level_by_total_xp(self, xp_total: int, expected: LevelInfo) -> None:
        assert level_for_xp(xp_total, CONFIG) == expected

    @pytest.mark.parametrize("level", range(1, 21))
    def test_level_and_threshold_agree(self, level: int) -> None:
        """Инвариант на переходах — единственном месте, которое игрок замечает."""
        info = level_for_xp(xp_threshold(level, CONFIG), CONFIG)
        step = xp_threshold(level + 1, CONFIG) - xp_threshold(level, CONFIG)

        assert info.level == level
        assert info.xp_into_level == 0
        assert info.xp_into_level + info.xp_to_next == step

    def test_negative_xp_rejected(self) -> None:
        with pytest.raises(ValueError, match="отрицательным"):
            level_for_xp(-1, CONFIG)


class TestXpConfigValidation:
    """Параметры кривой приходят из окружения, поэтому проверяются на входе."""

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"base_xp": 0}, "base_xp"),
            ({"target_seconds": 0}, "target_seconds"),
            ({"k_min": 0}, "k_min"),
            ({"k_min": 3.0, "k_max": 2.0}, "больше k_max"),
            ({"level_base_xp": 0}, "level_base_xp"),
            # Самая важная: growth < 1 привёл бы к нулевому шагу кривой
            # и вечному циклу в level_for_xp.
            ({"level_growth": 0.9}, "level_growth"),
        ],
    )
    def test_impossible_curve_params_rejected(self, kwargs: dict[str, float], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            XpConfig(**kwargs)  # type: ignore[arg-type]
