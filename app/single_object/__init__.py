"""Слой доступа к данным: весь SQL живёт здесь и только здесь.

Экземпляры создаются один раз: состояния объекты не хранят, сессия приходит
аргументом на каждый вызов.
"""

from app.single_object.games import GameObject
from app.single_object.players import PlayerObject

game_object = GameObject()
player_object = PlayerObject()

__all__ = ["GameObject", "PlayerObject", "game_object", "player_object"]
