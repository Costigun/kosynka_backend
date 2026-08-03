from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Ответ системных пробников.

    Literal, а не str: в контракте видно единственное допустимое значение,
    и опечатка в обработчике становится ошибкой типизации, а не сюрпризом
    для оркестратора.
    """

    status: Literal["ok"]
