"""
anti_abuse.py — Middleware aiogram для антиспама.
"""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from rate_limiter import limiter

log = logging.getLogger("anti_abuse")


class AntiAbuseMiddleware(BaseMiddleware):
    """
    Прозрачный middleware: проверяет rate limit перед каждым апдейтом.
    При нарушении — отправляет предупреждение и блокирует обработку.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Определяем user_id и объект для ответа
        user_id: int | None = None
        reply_obj = None

        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            reply_obj = event
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            reply_obj = event

        if user_id is None:
            return await handler(event, data)

        allowed, reason = limiter.check(user_id)
        if not allowed:
            log.debug("Blocked uid=%d: %s", user_id, reason)
            if reply_obj:
                try:
                    if isinstance(reply_obj, CallbackQuery):
                        await reply_obj.answer(reason, show_alert=True)
                    else:
                        await reply_obj.answer(reason)
                except Exception:
                    pass
            return  # прерываем цепочку

        return await handler(event, data)
