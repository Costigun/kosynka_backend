from typing import NoReturn

from fastapi import HTTPException, status


def raise_unauthorized() -> NoReturn:
    """Токена нет либо он неизвестен.

    Текст один и тот же для обоих случаев: подсказывать, существует ли токен,
    незачем.
    """
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def raise_player_not_found() -> NoReturn:
    """Игрока с таким признаком нет."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="player not found",
    )


def raise_game_not_found() -> NoReturn:
    """Партии нет либо она принадлежит другому игроку.

    Ответ одинаковый в обоих случаях намеренно: 403 на чужой партии сообщал бы,
    что она существует, — то есть позволял бы перебором нащупывать чужие
    идентификаторы.
    """
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="game not found",
    )
