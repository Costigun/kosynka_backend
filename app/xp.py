"""Формула опыта и кривая уровней.

ЧИСТЫЙ модуль: импортирует только стандартную библиотеку. Ни FastAPI, ни
SQLAlchemy, ни настроек — параметры приходят в ``XpConfig`` аргументом.
Зависимость идёт строго в одну сторону: ``config.py`` знает про ``xp.py``,
но не наоборот. Это ядро домена, и тестируется оно без окружения.
"""

from dataclasses import dataclass

# Версия формулы. Пишется в games.xp_formula_version каждой партии, чтобы
# начисленный опыт можно было пересчитать задним числом, зная, по каким
# правилам он был выдан. Меняешь формулу — увеличивай.
XP_FORMULA_VERSION = 1


@dataclass(frozen=True, slots=True)
class XpConfig:
    """Параметры кривой.

    Собирается вызывающим кодом из ``Settings``: сам модуль про переменные
    окружения не знает. Значения по умолчанию — рабочий баланс, а не заглушки.
    """

    # Опыт за «эталонную» партию — ту, что уложилась ровно в target_seconds.
    base_xp: int = 100
    # Эталонная длительность. Быстрее — коэффициент больше 1, медленнее — меньше.
    target_seconds: int = 300
    # Нижняя отсечка коэффициента. Не украшение: игра делается для человека,
    # который играет неспешно, и партия на час не должна давать ноль.
    k_min: float = 0.5
    # Верхняя отсечка. Принятое решение: duration_ms=1 даёт максимум ×2, а не ×100.
    k_max: float = 2.0
    # Стоимость второго уровня в опыте.
    level_base_xp: int = 200
    # Во сколько раз каждый следующий уровень дороже предыдущего.
    level_growth: float = 1.25

    def __post_init__(self) -> None:
        if self.base_xp < 1:
            raise ValueError("base_xp должен быть >= 1")
        if self.target_seconds < 1:
            raise ValueError("target_seconds должен быть >= 1")
        if self.k_min <= 0:
            raise ValueError("k_min должен быть > 0")
        if self.k_min > self.k_max:
            raise ValueError("k_min не может быть больше k_max")
        if self.level_base_xp < 1:
            raise ValueError("level_base_xp должен быть >= 1")
        # Самая важная проверка: при growth < 1 шаги кривой уменьшаются,
        # округление рано или поздно даёт ноль, и накопление в level_for_xp
        # никогда не дойдёт до xp_total — воркер зависнет навсегда.
        # Опечатка в переменной окружения не должна стоить сервиса.
        #
        # Ровно 1.0 не зависает, но стоит не дешевле: шаг перестаёт расти,
        # и level_for_xp превращается из логарифма в линейный перебор.
        # Замерено: при xp_total на потолке INTEGER это 10.7 млн итераций
        # и 0.75 секунды процессора НА КАЖДЫЙ запрос, считающий уровень, —
        # то есть на /players/me и на каждую победу. Граница строгая.
        if self.level_growth <= 1.0:
            raise ValueError("level_growth должен быть > 1.0")


@dataclass(frozen=True, slots=True)
class LevelInfo:
    """Уровень и положение внутри него. В базе не хранится — считается на выдаче."""

    level: int
    xp_into_level: int
    xp_to_next: int


def _round_half_up(value: float) -> int:
    """Округление «половина вверх».

    Встроенный round() в Python банковский: round(62.5) == 62. Для опыта это
    неожиданно и несимметрично, поэтому округляем явно. Не «упрощай» обратно —
    в tests/unit/test_xp.py есть опорная точка ровно на этот случай.
    """
    return int(value + 0.5)


def time_coefficient(duration_ms: int, config: XpConfig) -> float:
    """Коэффициент за скорость, зажатый с обеих сторон."""
    if duration_ms <= 0:
        # Ноль и отрицательное — это предел «мгновенно», а не ошибка. Схема
        # запроса такого не пропустит (ge=1), но чистая функция обязана быть
        # тотальной, иначе её нельзя тестировать в отрыве от API.
        return config.k_max

    coefficient = config.target_seconds / (duration_ms / 1000)
    return min(max(coefficient, config.k_min), config.k_max)


def xp_for_win(duration_ms: int, config: XpConfig) -> int:
    """Сколько опыта дать за победу длительностью duration_ms."""
    return _round_half_up(config.base_xp * time_coefficient(duration_ms, config))


def xp_threshold(level: int, config: XpConfig) -> int:
    """Суммарный опыт, необходимый для входа в уровень ``level``.

    Накопление идёт целыми числами, а не закрытой формулой с логарифмом:
    так level_for_xp(xp_threshold(L)) == L выполняется по построению, без
    плавающих пограничных ошибок ровно на переходах — то есть в единственном
    месте, которое игрок замечает.
    """
    if level <= 1:
        return 0

    total = 0
    step = float(config.level_base_xp)
    for _ in range(level - 1):
        total += _round_half_up(step)
        step *= config.level_growth
    return total


def level_for_xp(xp_total: int, config: XpConfig) -> LevelInfo:
    """Уровень и прогресс внутри него по суммарному опыту."""
    if xp_total < 0:
        raise ValueError("xp_total не может быть отрицательным")

    level = 1
    passed = 0
    step = float(config.level_base_xp)

    while True:
        cost = _round_half_up(step)
        if xp_total < passed + cost:
            return LevelInfo(
                level=level,
                xp_into_level=xp_total - passed,
                xp_to_next=passed + cost - xp_total,
            )
        passed += cost
        step *= config.level_growth
        level += 1
