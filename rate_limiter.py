"""
rate_limiter.py — In-memory rate limiting на asyncio.
"""

import asyncio
import time
import logging
from collections import defaultdict, deque

from config import (
    RATE_LIMIT_SECONDS,
    FLOOD_THRESHOLD,
    FLOOD_MUTE_MINUTES,
    ERROR_THRESHOLD,
)

log = logging.getLogger("rate_limiter")


class RateLimiter:
    """
    Глобальный rate limiter.
    Хранит:
      - last_request[uid]  — метка последнего запроса
      - flood_queue[uid]   — deque меток за последнюю минуту
      - muted_until[uid]   — Unix-время окончания мута
      - error_count[uid]   — счётчик ошибок подряд
      - blocked_until[uid] — блокировка за ошибки
    """

    def __init__(self) -> None:
        self._last:    dict[int, float]        = {}
        self._flood:   dict[int, deque]        = defaultdict(lambda: deque())
        self._muted:   dict[int, float]        = {}
        self._errors:  dict[int, int]          = defaultdict(int)
        self._blocked: dict[int, float]        = {}

    # ─────────────────────────────────────────
    # Публичный API
    # ─────────────────────────────────────────

    def check(self, user_id: int) -> tuple[bool, str]:
        """
        Возвращает (allowed, reason).
        reason — пустая строка если разрешено.
        """
        now = time.time()

        # 1. Блокировка за ошибки
        blocked_until = self._blocked.get(user_id, 0)
        if now < blocked_until:
            left = int(blocked_until - now)
            return False, f"⛔ Вы временно заблокированы. Подождите {left} сек."

        # 2. Мут за флуд
        muted_until = self._muted.get(user_id, 0)
        if now < muted_until:
            left = int(muted_until - now)
            return False, f"🚫 Слишком много запросов. Подождите {left} сек."

        # 3. Базовый rate limit (1 запрос / N секунд)
        last = self._last.get(user_id, 0)
        if now - last < RATE_LIMIT_SECONDS:
            wait = int(RATE_LIMIT_SECONDS - (now - last)) + 1
            return False, f"⏳ Подождите {wait} сек. перед следующим запросом."

        # 4. Flood detection (окно 60 секунд)
        dq = self._flood[user_id]
        while dq and now - dq[0] > 60:
            dq.popleft()
        dq.append(now)
        if len(dq) > FLOOD_THRESHOLD:
            mute_until = now + FLOOD_MUTE_MINUTES * 60
            self._muted[user_id] = mute_until
            log.warning("Флуд от %d — мут на %d мин.", user_id, FLOOD_MUTE_MINUTES)
            return False, f"🚫 Флуд-защита. Мут на {FLOOD_MUTE_MINUTES} мин."

        self._last[user_id] = now
        return True, ""

    def record_error(self, user_id: int) -> None:
        """Фиксирует ошибку; при достижении порога — блокирует."""
        self._errors[user_id] += 1
        if self._errors[user_id] >= ERROR_THRESHOLD:
            block_duration = 60 * self._errors[user_id]  # растёт с каждой волной
            self._blocked[user_id] = time.time() + block_duration
            log.warning(
                "Пользователь %d заблокирован на %ds после %d ошибок.",
                user_id,
                block_duration,
                self._errors[user_id],
            )

    def record_success(self, user_id: int) -> None:
        """Сбрасывает счётчик ошибок при успешном запросе."""
        self._errors[user_id] = 0


# Глобальный экземпляр
limiter = RateLimiter()
