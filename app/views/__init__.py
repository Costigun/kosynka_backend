"""Слой видов: доменные объекты → схемы ответа.

Экземпляры создаются здесь и переиспользуются: виды не хранят состояния,
плодить их на запрос незачем.
"""

from app.views.games import GameView
from app.views.players import PlayerView

game_view = GameView()
player_view = PlayerView()

__all__ = ["GameView", "PlayerView", "game_view", "player_view"]
