"""
main.py — Точка входа.

Порядок запуска:
  1. installer.ensure_packages()      — pip-пакеты
  2. installer.ensure_ffmpeg()        — статическая сборка FFmpeg
  3. Настройка логирования
  4. Инициализация БД
  5. Запуск бота (aiogram + dispatcher)
  6. Graceful shutdown
"""

# ──────────────────────────────────────────────────────────────
# Шаг 1: синхронная установка pip-пакетов (до импорта aiogram)
# ──────────────────────────────────────────────────────────────
import sys, os

# Добавляем проект в PYTHONPATH
sys.path.insert(0, os.path.dirname(__file__))

from installer import ensure_packages
ensure_packages()

# ──────────────────────────────────────────────────────────────
# Шаг 2: теперь можно импортировать внешние библиотеки
# ──────────────────────────────────────────────────────────────
import asyncio
import logging
import logging.handlers
import signal
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from installer import ensure_ffmpeg
from config import BOT_TOKEN, LOG_FILE, LOG_LEVEL
from database import init_db
from cleaner import clean_cache_sync, run_periodic_cleaner
from anti_abuse import AntiAbuseMiddleware
from menu_router import router


# ──────────────────────────────────────────────────────────────
# ЛОГИРОВАНИЕ
# ──────────────────────────────────────────────────────────────

def setup_logging() -> None:
    Path(LOG_FILE).parent.mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Консоль
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # Файл с ротацией
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


log = logging.getLogger("main")


# ──────────────────────────────────────────────────────────────
# ОСНОВНОЙ ЦИКЛ
# ──────────────────────────────────────────────────────────────

async def main() -> None:
    setup_logging()
    log.info("=== Запуск Telegram Music Bot ===")

    # Шаг 2: FFmpeg (асинхронно, с загрузкой при необходимости)
    await ensure_ffmpeg()

    # Шаг 3: БД
    await init_db()

    # Шаг 4: Очистка устаревшего кеша при старте
    removed = clean_cache_sync()
    if removed:
        log.info("При старте удалено %d устаревших файлов кеша.", removed)

    # Шаг 5: Создание бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.middleware(AntiAbuseMiddleware())
    dp.callback_query.middleware(AntiAbuseMiddleware())

    # Роутеры
    dp.include_router(router)

    # Фоновые задачи
    cleaner_task = asyncio.create_task(run_periodic_cleaner())

    # Graceful shutdown
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _shutdown_signal(sig):
        log.info("Получен сигнал %s, завершение...", sig.name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown_signal(s))
        except (NotImplementedError, OSError):
            # Windows не поддерживает add_signal_handler
            pass

    log.info("Бот запущен. Ожидаю апдейты...")
    try:
        polling_task = asyncio.create_task(
            dp.start_polling(bot, allowed_updates=["message", "callback_query"])
        )
        await asyncio.gather(polling_task, return_exceptions=True)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        log.info("Остановка бота...")
        cleaner_task.cancel()
        await bot.session.close()
        log.info("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[main] Прервано пользователем.")
