from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.meta import HealthResponse

# Пробники намеренно стоят вне цепочки слоёв: ни сервиса, ни вида, ни доступа
# к данным. /healthz обязан отвечать, даже когда всё остальное сломано, —
# любая зависимость здесь превращала бы чужой отказ в перезапуск контейнера.
router = APIRouter(tags=["meta"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Живость процесса.

    Базу намеренно НЕ трогает. Эта ручка отвечает на вопрос «жив ли процесс»,
    и по ней настроен liveness-пробник. Если бы она ходила в базу, моргнувший
    Postgres перезапускал бы все контейнеры разом — то есть превращал бы
    временную недоступность базы в полноценную аварию.
    """
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse)
async def readyz(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    """Готовность обслуживать запросы.

    Здесь база нужна: ``SELECT 1`` идёт через тот же пул, которым пользуется
    само приложение, поэтому проверка отражает реальное положение дел, а не
    доступность порта. Провал означает «не давайте мне трафик», а не
    «перезапустите меня».
    """
    try:
        await session.execute(text("SELECT 1"))
    # Except намеренно широкий: для пробника готовности любой сбой —
    # будь то отказ в подключении, таймаут или ошибка драйвера — равнозначен «не готов».
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return HealthResponse(status="ok")
