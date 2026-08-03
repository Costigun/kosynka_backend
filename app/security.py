import hashlib
import secrets

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.exceptions import raise_unauthorized
from app.models import Player
from app.single_object import player_object

# auto_error=False обязателен: со значением по умолчанию FastAPI отдаёт на
# отсутствующий заголовок 403, а контракт требует 401 и в этом случае тоже.
bearer_scheme = HTTPBearer(auto_error=False)


def generate_token() -> str:
    """Новый токен устройства.

    32 байта энтропии в urlsafe-виде. Показывается ровно один раз при
    регистрации: в базе хранится только sha256, и восстановить токен нельзя.
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """sha256 в hex — то, что лежит в колонке token_hash.

    Соль не нужна и была бы вредна: токен ищется по уникальному индексу, а
    случайных 32 байт достаточно, чтобы перебор был бессмысленным. Медленная
    KDF здесь тоже ни к чему — она замедлила бы каждый запрос, не добавив
    защиты значению, которое не является паролем и не выбирается человеком.
    """
    return hashlib.sha256(token.encode()).hexdigest()


async def current_player(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> Player:
    """Игрок, предъявивший токен.

    Сравнения через ``secrets.compare_digest`` здесь нет намеренно: мы не
    сравниваем секрет со секретом, а ищем по индексу хеш предъявленного
    значения. Атакующий и так знает то, что подставил.
    """
    if credentials is None:
        raise_unauthorized()

    # raise_exception=True (по умолчанию): неизвестный токен превращается
    # в 401 внутри слоя доступа, здесь проверять нечего.
    return await player_object.get_by_token_hash(
        session=session, token_hash=hash_token(credentials.credentials)
    )
