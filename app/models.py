from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс моделей.

    Таблиц пока нет: игрок и партия появятся вместе с регистрацией устройства
    и начислением опыта. Класс нужен уже сейчас, потому что на ``Base.metadata``
    смотрит ``alembic check`` — без него автогенерация не с чем сравнивать.
    """
