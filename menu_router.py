"""
menu_router.py — Все роутеры: /start, меню, поиск, топ, история, плейлисты, настройки.
"""

import asyncio
import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
)

import database as db
import playlists as pl
import stats as stats_mod
import history as hist_mod
from downloader import search_and_download, search_list, download_by_url
from rate_limiter import limiter
from top_engine import get_global_top, get_trending, format_top_list
from wave_engine import build_wave
import ui

log = logging.getLogger("menu_router")
router = Router()


# ─────────────────────────────────────────────
# FSM
# ─────────────────────────────────────────────

class SearchFSM(StatesGroup):
    waiting_query   = State()
    showing_results = State()   # пользователь видит список, ждём выбора


class PlaylistFSM(StatesGroup):
    waiting_name = State()
    waiting_rename = State()


# ─────────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────────

async def _ensure_user(tg_user) -> int:
    return await db.upsert_user(tg_user.id, tg_user.username)


async def _edit_or_send(message: Message, text: str, reply_markup=None, **kwargs) -> Message:
    """Пытается edit_text, при ошибке — answer."""
    try:
        return await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup, **kwargs)
    except Exception:
        return await message.answer(text, parse_mode="HTML", reply_markup=reply_markup, **kwargs)


async def _send_main_menu(target, **kwargs):
    """Отправляет главное меню в зависимости от типа target."""
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(
            ui.MAIN_MENU_TEXT,
            parse_mode="HTML",
            reply_markup=ui.main_menu_kb(),
        )
    else:
        await target.answer(
            ui.MAIN_MENU_TEXT,
            parse_mode="HTML",
            reply_markup=ui.main_menu_kb(),
        )


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _ensure_user(message.from_user)
    await _send_main_menu(message)


# ─────────────────────────────────────────────
# НАВИГАЦИЯ ПО МЕНЮ
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:main")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await _send_main_menu(cb)


# ─────────────────────────────────────────────
# ПОИСК
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:search")
async def cb_search(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(SearchFSM.waiting_query)
    await cb.message.edit_text(
        "🔍 <b>Поиск трека</b>\n\nВведите название песни или исполнителя:",
        parse_mode="HTML",
        reply_markup=ui.cancel_search_kb(),
    )


async def _do_search(message: Message, state: FSMContext, query: str) -> None:
    """Общая логика поиска: показать список результатов."""
    await state.clear()

    wait_msg = await message.answer("🔎 Ищу треки...")

    try:
        results = await search_list(query, count=5)
    except Exception as e:
        log.exception("Ошибка поиска: %s", e)
        limiter.record_error(message.from_user.id)
        await wait_msg.edit_text("❌ Ошибка при поиске. Попробуйте позже.", reply_markup=ui.back_to_main_kb())
        return

    if not results:
        limiter.record_error(message.from_user.id)
        await wait_msg.edit_text(
            "😕 Ничего не найдено. Попробуйте другой запрос.",
            reply_markup=ui.back_to_main_kb(),
        )
        return

    limiter.record_success(message.from_user.id)

    # Сохраняем результаты в FSM и переходим в состояние выбора
    await state.set_state(SearchFSM.showing_results)
    await state.update_data(results=results, query=query)

    lines = [f"🔍 <b>Результаты по запросу:</b> <i>{query}</i>\n"]
    for i, t in enumerate(results, 1):
        title = t.get("title", "?")
        perf  = t.get("performer", "")
        dur   = t.get("duration", 0)
        mins, sec = divmod(dur, 60)
        dur_str = f"{mins}:{sec:02d}" if dur else "?:??"
        lines.append(f"{i}. <b>{perf}</b> — {title}  <code>[{dur_str}]</code>")

    await wait_msg.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=ui.search_results_kb(results),
    )


@router.message(SearchFSM.waiting_query)
async def handle_search_query(message: Message, state: FSMContext) -> None:
    query = message.text.strip()
    if not query:
        return
    await _do_search(message, state, query)


@router.callback_query(F.data.startswith("pick:"), SearchFSM.showing_results)
async def cb_pick_track(cb: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал трек из списка."""
    idx = int(cb.data.split(":")[1])
    data = await state.get_data()
    results: list[dict] = data.get("results", [])

    if idx >= len(results):
        await cb.answer("❌ Трек не найден.", show_alert=True)
        return

    chosen = results[idx]
    await cb.answer("⏳ Скачиваю...")
    await state.clear()

    user_id = await _ensure_user(cb.from_user)

    wait_msg = await cb.message.edit_text(
        f"⏳ Скачиваю: <b>{chosen['performer']} — {chosen['title']}</b>",
        parse_mode="HTML",
    )

    try:
        track = await download_by_url(
            url=chosen["url"],
            track_hash=chosen["track_hash"],
            title=chosen["title"],
            performer=chosen["performer"],
            duration=chosen["duration"],
        )
    except Exception as e:
        log.exception("Ошибка скачивания: %s", e)
        track = None

    if not track:
        limiter.record_error(cb.from_user.id)
        await wait_msg.edit_text("❌ Не удалось скачать трек. Попробуйте другой.", reply_markup=ui.back_to_main_kb())
        return

    limiter.record_success(cb.from_user.id)

    await db.upsert_track(track["track_hash"], track["title"], track["performer"], track["duration"])
    await db.increment_unique_user(track["track_hash"], user_id)
    await hist_mod.record_play(user_id, track["track_hash"])

    await wait_msg.delete()
    audio_file = FSInputFile(track["file_path"])
    await cb.message.answer_audio(
        audio=audio_file,
        title=track["title"],
        performer=track["performer"],
        duration=track["duration"],
        reply_markup=ui.back_to_main_kb(),
    )


# ─────────────────────────────────────────────
# ТОП
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:top")
async def cb_top_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "🔥 <b>Топ треков</b>\n\nВыберите список:",
        parse_mode="HTML",
        reply_markup=ui.top_menu_kb(),
    )


@router.callback_query(F.data == "top:global")
async def cb_top_global(cb: CallbackQuery) -> None:
    await cb.answer()
    tracks = await get_global_top()
    text = format_top_list(tracks, "🏆 <b>Глобальный топ</b>")
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=ui.top_tracks_kb(tracks, "dl_hash") if tracks else ui.top_menu_kb(),
    )


@router.callback_query(F.data == "top:trending")
async def cb_top_trending(cb: CallbackQuery) -> None:
    await cb.answer()
    tracks = await get_trending()
    text = format_top_list(tracks, "🔥 <b>Trending 24ч</b>")
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=ui.top_tracks_kb(tracks, "dl_hash") if tracks else ui.top_menu_kb(),
    )


# ─────────────────────────────────────────────
# ИСТОРИЯ
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:history")
async def cb_history(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    tracks = await hist_mod.get_user_history(user_id, limit=20)

    if not tracks:
        await cb.message.edit_text(
            "🕘 <b>История</b>\n\n<i>Вы ещё ничего не слушали.</i>",
            parse_mode="HTML",
            reply_markup=ui.back_to_main_kb(),
        )
        return

    await cb.message.edit_text(
        "🕘 <b>История прослушиваний</b>\n\nНажмите на трек для скачивания:",
        parse_mode="HTML",
        reply_markup=ui.history_kb(tracks),
    )


# ─────────────────────────────────────────────
# СКАЧАТЬ ПО ХЕШУ (из топа, истории, волны)
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("dl_hash:"))
async def cb_download_by_hash(cb: CallbackQuery) -> None:
    await cb.answer("⏳ Загружаю...")
    track_hash = cb.data.split(":", 1)[1]
    user_id = await _ensure_user(cb.from_user)

    # Ищем мета в БД
    track_info = await db.get_track(track_hash)
    if not track_info:
        await cb.message.answer("❌ Трек не найден в базе данных.")
        return

    # Проверяем кеш
    from config import CACHE_DIR
    mp3_path = Path(CACHE_DIR) / f"{track_hash}.mp3"

    if not mp3_path.exists():
        # Пытаемся найти трек заново
        query = f"{track_info.get('performer','')} {track_info.get('title','')}".strip()
        wait_msg = await cb.message.answer("🔎 Кеш устарел, ищу трек заново...")
        try:
            track = await search_and_download(query)
        except Exception as e:
            log.error("Ошибка повторного поиска: %s", e)
            track = None
        await wait_msg.delete()
        if not track:
            await cb.message.answer("❌ Не удалось найти трек.")
            return
        mp3_path = Path(track["file_path"])
        await db.upsert_track(track["track_hash"], track["title"], track["performer"], track["duration"])

    await hist_mod.record_play(user_id, track_hash)
    await db.increment_unique_user(track_hash, user_id)

    audio_file = FSInputFile(str(mp3_path))
    await cb.message.answer_audio(
        audio=audio_file,
        title=track_info.get("title", ""),
        performer=track_info.get("performer", ""),
        duration=track_info.get("duration", 0),
    )


# ─────────────────────────────────────────────
# МОЯ ВОЛНА
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:wave")
async def cb_wave(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    tracks = await build_wave(user_id)

    if not tracks:
        await cb.message.edit_text(
            "🌊 <b>Моя волна</b>\n\n"
            "<i>Пока недостаточно данных. Слушайте больше музыки!</i>",
            parse_mode="HTML",
            reply_markup=ui.back_to_main_kb(),
        )
        return

    lines = ["🌊 <b>Моя волна</b>\n\nПодборка для вас:"]
    for i, t in enumerate(tracks, 1):
        title = t.get("title") or "?"
        perf = t.get("performer") or ""
        lines.append(f"{i}. {perf} — {title}" if perf else f"{i}. {title}")

    await cb.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=ui.wave_results_kb(tracks),
    )


# ─────────────────────────────────────────────
# СТАТИСТИКА
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:stats")
async def cb_stats(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    s = await stats_mod.get_user_stats(cb.from_user.id, user_id)
    text = stats_mod.format_stats(s)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=ui.back_to_main_kb())


# ─────────────────────────────────────────────
# ПЛЕЙЛИСТЫ
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:playlists")
async def cb_playlists_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "🎼 <b>Плейлисты</b>",
        parse_mode="HTML",
        reply_markup=ui.playlists_menu_kb(),
    )


@router.callback_query(F.data == "pl:list")
async def cb_pl_list(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    playlists = await pl.list_playlists(user_id)
    if not playlists:
        await cb.message.edit_text(
            "🎼 <b>Мои плейлисты</b>\n\n<i>У вас нет плейлистов.</i>",
            parse_mode="HTML",
            reply_markup=ui.playlists_menu_kb(),
        )
        return
    await cb.message.edit_text(
        "🎼 <b>Мои плейлисты</b>\n\nВыберите плейлист:",
        parse_mode="HTML",
        reply_markup=ui.playlists_list_kb(playlists),
    )


@router.callback_query(F.data == "pl:create")
async def cb_pl_create(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(PlaylistFSM.waiting_name)
    await cb.message.edit_text(
        "🎼 Введите название нового плейлиста:",
        reply_markup=ui.cancel_search_kb(),
    )


@router.message(PlaylistFSM.waiting_name)
async def handle_pl_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        return
    await state.clear()
    user_id = await _ensure_user(message.from_user)
    pl_id = await pl.create(user_id, name)
    if pl_id is None:
        await message.answer(
            "❌ Достигнут лимит плейлистов (10).",
            reply_markup=ui.back_to_main_kb(),
        )
    else:
        await message.answer(
            f"✅ Плейлист <b>{name}</b> создан!",
            parse_mode="HTML",
            reply_markup=ui.back_to_main_kb(),
        )


@router.callback_query(F.data.startswith("pl:open:"))
async def cb_pl_open(cb: CallbackQuery) -> None:
    await cb.answer()
    pl_id = int(cb.data.split(":")[2])
    user_id = await _ensure_user(cb.from_user)
    playlist = await pl.get(pl_id, user_id)
    if not playlist:
        await cb.message.edit_text("❌ Плейлист не найден.", reply_markup=ui.back_to_main_kb())
        return
    tracks = await pl.get_tracks(pl_id)
    count = len(tracks)
    await cb.message.edit_text(
        f"🎼 <b>{playlist['name']}</b>\n\n{count} треков",
        parse_mode="HTML",
        reply_markup=ui.playlist_detail_kb(pl_id),
    )


@router.callback_query(F.data.startswith("pl:delete:"))
async def cb_pl_delete(cb: CallbackQuery) -> None:
    await cb.answer()
    pl_id = int(cb.data.split(":")[2])
    user_id = await _ensure_user(cb.from_user)
    await cb.message.edit_text(
        "❓ Удалить плейлист? Это действие необратимо.",
        reply_markup=ui.confirm_kb(f"pl:delete_confirm:{pl_id}", "pl:list"),
    )


@router.callback_query(F.data.startswith("pl:delete_confirm:"))
async def cb_pl_delete_confirm(cb: CallbackQuery) -> None:
    await cb.answer()
    pl_id = int(cb.data.split(":")[2])
    user_id = await _ensure_user(cb.from_user)
    ok = await pl.delete(pl_id, user_id)
    msg = "✅ Плейлист удалён." if ok else "❌ Плейлист не найден."
    await cb.message.edit_text(msg, reply_markup=ui.back_to_main_kb())


@router.callback_query(F.data.startswith("pl:rename:"))
async def cb_pl_rename(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    pl_id = int(cb.data.split(":")[2])
    await state.set_state(PlaylistFSM.waiting_rename)
    await state.update_data(pl_id=pl_id)
    await cb.message.edit_text(
        "✏ Введите новое название плейлиста:",
        reply_markup=ui.cancel_search_kb(),
    )


@router.message(PlaylistFSM.waiting_rename)
async def handle_pl_rename(message: Message, state: FSMContext) -> None:
    new_name = message.text.strip()
    if not new_name:
        return
    data = await state.get_data()
    pl_id = data.get("pl_id")
    await state.clear()
    user_id = await _ensure_user(message.from_user)
    ok = await pl.rename(pl_id, user_id, new_name)
    msg = f"✅ Переименован в <b>{new_name}</b>." if ok else "❌ Ошибка переименования."
    await message.answer(msg, parse_mode="HTML", reply_markup=ui.back_to_main_kb())


@router.callback_query(F.data.startswith("pl:play:"))
async def cb_pl_play(cb: CallbackQuery) -> None:
    await cb.answer("⏳ Загружаю плейлист...")
    pl_id = int(cb.data.split(":")[2])
    user_id = await _ensure_user(cb.from_user)
    tracks = await pl.get_tracks(pl_id)
    if not tracks:
        await cb.message.answer("ℹ️ Плейлист пустой.")
        return
    await cb.message.answer(f"▶ Воспроизведение плейлиста: {len(tracks)} треков.\n(Треки будут отправлены по одному)")
    for t in tracks[:10]:  # ограничение Telegram на кол-во сообщений подряд
        from config import CACHE_DIR
        mp3_path = Path(CACHE_DIR) / f"{t['track_hash']}.mp3"
        if mp3_path.exists():
            audio_file = FSInputFile(str(mp3_path))
            await cb.message.answer_audio(
                audio=audio_file,
                title=t.get("title", ""),
                performer=t.get("performer", ""),
                duration=t.get("duration", 0),
            )
            await asyncio.sleep(0.5)


@router.callback_query(F.data.startswith("pl:rmtrack:"))
async def cb_pl_rmtrack(cb: CallbackQuery) -> None:
    await cb.answer()
    parts = cb.data.split(":")
    pl_id = int(parts[2])
    hash_prefix = parts[3]
    user_id = await _ensure_user(cb.from_user)
    # Находим полный хеш
    tracks = await pl.get_tracks(pl_id)
    full_hash = next((t["track_hash"] for t in tracks if t["track_hash"].startswith(hash_prefix)), None)
    if full_hash:
        await pl.remove_track(pl_id, user_id, full_hash)
        await cb.message.answer("✅ Трек удалён из плейлиста.", reply_markup=ui.back_to_main_kb())
    else:
        await cb.message.answer("❌ Трек не найден.")


# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "⚙ <b>Настройки</b>",
        parse_mode="HTML",
        reply_markup=ui.settings_kb(),
    )


@router.callback_query(F.data == "settings:clear_history")
async def cb_clear_history(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "❓ Очистить всю историю прослушиваний?",
        reply_markup=ui.confirm_kb("settings:clear_history_confirm", "menu:settings"),
    )


@router.callback_query(F.data == "settings:clear_history_confirm")
async def cb_clear_history_confirm(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    async with db.get_db() as conn:
        await conn.execute("DELETE FROM history WHERE user_id=?", (user_id,))
        await conn.commit()
    await cb.message.edit_text("✅ История очищена.", reply_markup=ui.back_to_main_kb())


# ─────────────────────────────────────────────
# ПОИСК ВНЕ МЕНЮ (любой текст без активного FSM)
# ─────────────────────────────────────────────

@router.message(F.text, ~F.text.startswith("/"))
async def handle_freetext_search(message: Message, state: FSMContext) -> None:
    """
    Любое текстовое сообщение вне FSM запускает поиск.
    Команды (начинающиеся с /) — игнорируются этим хендлером.
    """
    current_state = await state.get_state()
    # Если уже в каком-либо FSM — не перехватываем
    if current_state is not None:
        return

    await _ensure_user(message.from_user)
    query = message.text.strip()
    if not query:
        return

    await _do_search(message, state, query)
