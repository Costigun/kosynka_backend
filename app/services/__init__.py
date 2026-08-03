"""Слой сервисов: оркестрация между доступом к данным и сборкой ответа.

Экземпляры создаются здесь и импортируются роутами готовыми — инстанцировать
на запрос нечего, состояния сервисы не хранят.
"""

from app.services.games import GameService
from app.services.players import PlayerService

game_service = GameService()
player_service = PlayerService()

__all__ = ["GameService", "PlayerService", "game_service", "player_service"]
