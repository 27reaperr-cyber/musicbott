"""
rate_limiter.py — In-memory rate limiting на asyncio.
"""

import asyncio
import time
import logging
from collections import defaultdict

from config import (
    RATE_LIMIT_SECONDS,
    ERROR_THRESHOLD,
)

log = logging.getLogger("rate_limiter")


class RateLimiter:
    """
    Rate limiter без флуд-мута.
    Хранит:
      - last_request[uid]  — метка последнего запроса
      - error_count[uid]   — счётчик ошибок подряд
      - blocked_until[uid] — блокировка за ошибки
    """

    def __init__(self) -> None:
        self._last:    dict[int, float] = {}
        self._errors:  dict[int, int]   = defaultdict(int)
        self._blocked: dict[int, float] = {}

    def check(self, user_id: int) -> tuple[bool, str]:
        """Возвращает (allowed, reason)."""
        now = time.time()

        # 1. Блокировка за ошибки
        blocked_until = self._blocked.get(user_id, 0)
        if now < blocked_until:
            left = int(blocked_until - now)
            return False, f"⛔ Вы временно заблокированы. Подождите {left} сек."

        # 2. Базовый rate limit (1 запрос / N секунд)
        last = self._last.get(user_id, 0)
        if now - last < RATE_LIMIT_SECONDS:
            wait = int(RATE_LIMIT_SECONDS - (now - last)) + 1
            return False, f"⏳ Подождите {wait} сек. перед следующим запросом."

        self._last[user_id] = now
        return True, ""

    def record_error(self, user_id: int) -> None:
        self._errors[user_id] += 1
        if self._errors[user_id] >= ERROR_THRESHOLD:
            block_duration = 60 * self._errors[user_id]
            self._blocked[user_id] = time.time() + block_duration
            log.warning(
                "Пользователь %d заблокирован на %ds после %d ошибок.",
                user_id, block_duration, self._errors[user_id],
            )

    def record_success(self, user_id: int) -> None:
        self._errors[user_id] = 0


# Глобальный экземпляр
limiter = RateLimiter()
