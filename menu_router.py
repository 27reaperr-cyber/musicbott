"""
menu_router.py — Все хендлеры бота Dreinnify.
"""

import asyncio
import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile

import database as db
import playlists as pl
import stats as stats_mod
import history as hist_mod
from downloader import search_list, download_by_url, process_speed, search_and_download
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
    showing_results = State()


class PlaylistFSM(StatesGroup):
    waiting_name   = State()
    waiting_rename = State()


# ─────────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────────

async def _ensure_user(tg_user) -> int:
    return await db.upsert_user(tg_user.id, tg_user.username)


async def _send_main_menu(target):
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(
                ui.MAIN_MENU_TEXT, parse_mode="HTML", reply_markup=ui.main_menu_kb()
            )
        except Exception:
            await target.message.answer(
                ui.MAIN_MENU_TEXT, parse_mode="HTML", reply_markup=ui.main_menu_kb()
            )
    else:
        await target.answer(
            ui.MAIN_MENU_TEXT, parse_mode="HTML", reply_markup=ui.main_menu_kb()
        )


async def _send_track(
    message: Message,
    track,
    user_id: int,
    from_cb: bool = False,
) -> None:
    """
    Отправляет аудио и сохраняет в историю.
    Под треком — кнопки Speed Up / Slowed / В плейлист.
    Без кнопки «Главное меню» — она удалила бы аудио-сообщение.
    """
    await db.upsert_track(track["track_hash"], track["title"], track["performer"], track["duration"])
    await db.increment_unique_user(track["track_hash"], user_id)
    await hist_mod.record_play(user_id, track["track_hash"])

    audio_file = FSInputFile(track["file_path"])
    await message.answer_audio(
        audio=audio_file,
        title=track["title"],
        performer=track["performer"],
        duration=track["duration"],
        reply_markup=ui.track_actions_kb(track["track_hash"]),
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
# ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:main")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await _send_main_menu(cb)


@router.callback_query(F.data == "search:cancel")
async def cb_search_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await _send_main_menu(cb)


# ─────────────────────────────────────────────
# ПОИСК
# ─────────────────────────────────────────────

async def _do_search(message: Message, state: FSMContext, query: str) -> None:
    await state.clear()
    wait_msg = await message.answer("🔎 Ищу треки...")

    try:
        results = await search_list(query, count=7)
    except Exception as e:
        log.exception("Ошибка поиска: %s", e)
        limiter.record_error(message.from_user.id)
        await wait_msg.edit_text("❌ Ошибка при поиске. Попробуйте позже.", reply_markup=ui.back_to_main_kb())
        return

    if not results:
        limiter.record_error(message.from_user.id)
        await wait_msg.edit_text("😕 Ничего не найдено. Попробуйте другой запрос.", reply_markup=ui.back_to_main_kb())
        return

    limiter.record_success(message.from_user.id)
    await state.set_state(SearchFSM.showing_results)
    await state.update_data(results=results, query=query)

    lines = [f"🔍 <b>Результаты:</b> <i>{query}</i>\n"]
    for i, t in enumerate(results, 1):
        dur = t.get("duration", 0)
        m, s = divmod(dur, 60)
        dur_str = f"{m}:{s:02d}" if dur else "?:??"
        perf  = t.get("performer", "")
        title = t.get("title", "?")
        lines.append(f"{i}. <b>{perf}</b> — {title}  <code>[{dur_str}]</code>")

    await wait_msg.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=ui.search_results_kb(results),
    )


@router.message(SearchFSM.waiting_query)
async def handle_search_query(message: Message, state: FSMContext) -> None:
    query = message.text.strip()
    if query:
        await _do_search(message, state, query)


@router.callback_query(F.data.startswith("pick:"), SearchFSM.showing_results)
async def cb_pick_track(cb: CallbackQuery, state: FSMContext) -> None:
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
        f"⏳ <b>{chosen['performer']} — {chosen['title']}</b>\n\nСкачиваю...",
        parse_mode="HTML",
    )

    try:
        track = await download_by_url(
            url=chosen["url"], track_hash=chosen["track_hash"],
            title=chosen["title"], performer=chosen["performer"], duration=chosen["duration"],
        )
    except Exception as e:
        log.exception("Ошибка скачивания: %s", e)
        track = None

    if not track:
        limiter.record_error(cb.from_user.id)
        await wait_msg.edit_text("❌ Не удалось скачать трек. Попробуйте другой.", reply_markup=ui.back_to_main_kb())
        return

    limiter.record_success(cb.from_user.id)
    await wait_msg.delete()
    await _send_track(cb.message, track, user_id)


# ─────────────────────────────────────────────
# СКОРОСТЬ / ТОНАЛЬНОСТЬ
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("speed:"))
async def cb_speed(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    mode       = parts[1]   # 'up' или 'slo'
    track_hash = parts[2]

    labels = {"up": "⚡ Speed Up (×1.2)", "slo": "🌊 Slowed (×0.8)"}
    label  = labels.get(mode, "Обработка")

    await cb.answer(f"⏳ Применяю {label}...")

    track_info = await db.get_track(track_hash)
    if not track_info:
        await cb.message.answer("❌ Трек не найден в базе данных.")
        return

    # Проверяем наличие исходника
    from config import CACHE_DIR
    src = Path(CACHE_DIR) / f"{track_hash}.mp3"
    if not src.exists():
        # Пробуем заново скачать
        wait_msg = await cb.message.answer("⏳ Исходник не найден, скачиваю...")
        q = f"{track_info.get('performer','')} {track_info.get('title','')}".strip()
        track = await search_and_download(q)
        await wait_msg.delete()
        if not track:
            await cb.message.answer("❌ Не удалось загрузить трек для обработки.")
            return

    proc_msg = await cb.message.answer(f"⚙ Обрабатываю: <b>{label}</b>...", parse_mode="HTML")

    out_path = await process_speed(track_hash, mode)
    await proc_msg.delete()

    if not out_path:
        await cb.message.answer("❌ Ошибка при обработке. Попробуйте позже.")
        return

    # Длительность меняется при изменении скорости
    orig_dur = track_info.get("duration", 0)
    speed_factor = 1.2 if mode == "up" else 0.8
    new_dur = int(orig_dur / speed_factor) if orig_dur else 0

    title_suffix = " (Speed Up)" if mode == "up" else " (Slowed)"
    audio_file = FSInputFile(out_path)
    await cb.message.answer_audio(
        audio=audio_file,
        title=(track_info.get("title") or "") + title_suffix,
        performer=track_info.get("performer") or "",
        duration=new_dur,
        reply_markup=ui.speed_done_kb(track_hash),
    )


# ─────────────────────────────────────────────
# ДОБАВИТЬ В ПЛЕЙЛИСТ (из трека)
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("addpl:"))
async def cb_addpl_pick(cb: CallbackQuery) -> None:
    """Показывает список плейлистов для добавления трека."""
    track_hash = cb.data.split(":", 1)[1]
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    playlists = await pl.list_playlists(user_id)

    if not playlists:
        await cb.message.answer(
            "🎼 У вас нет плейлистов.\n\nСоздайте плейлист через меню → Плейлисты.",
            reply_markup=ui.back_to_main_kb(),
        )
        return

    await cb.message.answer(
        "🎼 <b>В какой плейлист добавить трек?</b>",
        parse_mode="HTML",
        reply_markup=ui.select_playlist_for_add_kb(playlists, track_hash),
    )


@router.callback_query(F.data.startswith("addpl_c:"))
async def cb_addpl_confirm(cb: CallbackQuery) -> None:
    """Добавляет трек в выбранный плейлист."""
    _, pl_id_str, track_hash = cb.data.split(":", 2)
    pl_id = int(pl_id_str)
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)

    result = await pl.add_track(pl_id, user_id, track_hash)
    messages = {
        "ok":        "✅ Трек добавлен в плейлист!",
        "duplicate": "ℹ️ Трек уже есть в этом плейлисте.",
        "limit":     "❌ Плейлист заполнен (максимум 200 треков).",
        "not_found": "❌ Плейлист не найден.",
    }
    await cb.message.edit_text(messages.get(result, "❌ Ошибка."), reply_markup=ui.back_to_main_kb())


@router.callback_query(F.data == "addpl_cancel")
async def cb_addpl_cancel(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.delete()


# ─────────────────────────────────────────────
# СКАЧАТЬ ПО ХЕШУ (история / топ / волна)
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("dl_hash:"))
async def cb_download_by_hash(cb: CallbackQuery) -> None:
    await cb.answer("⏳ Загружаю...")
    track_hash = cb.data.split(":", 1)[1]
    user_id = await _ensure_user(cb.from_user)

    track_info = await db.get_track(track_hash)
    if not track_info:
        await cb.message.answer("❌ Трек не найден.")
        return

    from config import CACHE_DIR
    mp3_path = Path(CACHE_DIR) / f"{track_hash}.mp3"

    if not mp3_path.exists():
        q = f"{track_info.get('performer','')} {track_info.get('title','')}".strip()
        wait_msg = await cb.message.answer("⏳ Скачиваю...")
        try:
            track = await search_and_download(q)
        except Exception:
            track = None
        await wait_msg.delete()
        if not track:
            await cb.message.answer("❌ Не удалось найти трек.")
            return
        track_info = {"track_hash": track["track_hash"], "title": track["title"],
                      "performer": track["performer"], "duration": track["duration"],
                      "file_path": track["file_path"]}
        mp3_path = Path(track["file_path"])
    else:
        track_info["file_path"] = str(mp3_path)

    audio_file = FSInputFile(str(mp3_path))
    await db.increment_unique_user(track_hash, user_id)
    await hist_mod.record_play(user_id, track_hash)

    await cb.message.answer_audio(
        audio=audio_file,
        title=track_info.get("title", ""),
        performer=track_info.get("performer", ""),
        duration=track_info.get("duration", 0),
        reply_markup=ui.track_actions_kb(track_hash),
    )


# ─────────────────────────────────────────────
# ТОП
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:top")
async def cb_top_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "🔥 <b>Топ треков</b>",
        parse_mode="HTML", reply_markup=ui.top_menu_kb(),
    )


@router.callback_query(F.data == "top:global")
async def cb_top_global(cb: CallbackQuery) -> None:
    await cb.answer()
    tracks = await get_global_top()
    text = format_top_list(tracks, "🏆 <b>Глобальный топ</b>")
    kb = ui.top_tracks_kb(tracks, "dl_hash") if tracks else ui.top_menu_kb()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


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
            parse_mode="HTML", reply_markup=ui.back_to_main_kb(),
        )
        return
    await cb.message.edit_text(
        "🕘 <b>История прослушиваний</b>\n\nНажмите на трек:",
        parse_mode="HTML", reply_markup=ui.history_kb(tracks),
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
            "🌊 <b>Моя волна</b>\n\n<i>Слушайте больше музыки для персонализации!</i>",
            parse_mode="HTML", reply_markup=ui.back_to_main_kb(),
        )
        return
    lines = ["🌊 <b>Моя волна</b>\n"]
    for i, t in enumerate(tracks, 1):
        perf  = t.get("performer", "")
        title = t.get("title", "?")
        lines.append(f"{i}. {perf} — {title}" if perf else f"{i}. {title}")
    await cb.message.edit_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=ui.wave_results_kb(tracks),
    )


# ─────────────────────────────────────────────
# СТАТИСТИКА
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:stats")
async def cb_stats(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    s = await stats_mod.get_user_stats(cb.from_user.id, user_id)
    await cb.message.edit_text(stats_mod.format_stats(s), parse_mode="HTML", reply_markup=ui.back_to_main_kb())


# ─────────────────────────────────────────────
# ПЛЕЙЛИСТЫ
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:playlists")
async def cb_playlists_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "🎼 <b>Плейлисты</b>", parse_mode="HTML", reply_markup=ui.playlists_menu_kb()
    )


@router.callback_query(F.data == "pl:list")
async def cb_pl_list(cb: CallbackQuery) -> None:
    await cb.answer()
    user_id = await _ensure_user(cb.from_user)
    playlists = await pl.list_playlists(user_id)
    if not playlists:
        await cb.message.edit_text(
            "🎼 <b>Мои плейлисты</b>\n\n<i>У вас нет плейлистов.</i>",
            parse_mode="HTML", reply_markup=ui.playlists_menu_kb(),
        )
        return
    await cb.message.edit_text(
        "🎼 <b>Мои плейлисты</b>", parse_mode="HTML",
        reply_markup=ui.playlists_list_kb(playlists),
    )


@router.callback_query(F.data == "pl:create")
async def cb_pl_create(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(PlaylistFSM.waiting_name)
    await cb.message.edit_text("🎼 Введите название нового плейлиста:", reply_markup=ui.cancel_search_kb())


@router.message(PlaylistFSM.waiting_name)
async def handle_pl_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        return
    await state.clear()
    user_id = await _ensure_user(message.from_user)
    pl_id = await pl.create(user_id, name)
    if pl_id is None:
        await message.answer("❌ Достигнут лимит плейлистов (10).", reply_markup=ui.back_to_main_kb())
    else:
        await message.answer(
            f"✅ Плейлист <b>{name}</b> создан!\n\nДобавляйте треки кнопкой «➕ В плейлист» под любым треком.",
            parse_mode="HTML", reply_markup=ui.back_to_main_kb(),
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
    count  = len(tracks)
    await cb.message.edit_text(
        f"🎼 <b>{playlist['name']}</b>\n\n{count} треков",
        parse_mode="HTML",
        reply_markup=ui.playlist_detail_kb(pl_id, count),
    )


@router.callback_query(F.data.startswith("pl:tracks:"))
async def cb_pl_tracks(cb: CallbackQuery) -> None:
    """Список треков плейлиста с кнопками удаления и пагинацией."""
    await cb.answer()
    parts = cb.data.split(":")
    pl_id = int(parts[2])
    page  = int(parts[3]) if len(parts) > 3 else 0

    user_id = await _ensure_user(cb.from_user)
    playlist = await pl.get(pl_id, user_id)
    if not playlist:
        await cb.message.edit_text("❌ Плейлист не найден.", reply_markup=ui.back_to_main_kb())
        return

    tracks = await pl.get_tracks(pl_id)
    if not tracks:
        await cb.message.edit_text(
            f"🎼 <b>{playlist['name']}</b>\n\n<i>Плейлист пустой.</i>",
            parse_mode="HTML",
            reply_markup=ui.playlist_detail_kb(pl_id, 0),
        )
        return

    per_page = 8
    start = page * per_page
    end   = start + per_page
    page_tracks = tracks[start:end]
    total_pages = (len(tracks) - 1) // per_page + 1

    lines = [f"🎼 <b>{playlist['name']}</b>  ({len(tracks)} тр.)"]
    lines.append(f"<i>Страница {page+1}/{total_pages} — нажмите ❌ чтобы удалить</i>\n")
    for i, t in enumerate(page_tracks, start + 1):
        perf  = t.get("performer", "")
        title = t.get("title", "?")
        lines.append(f"{i}. {perf} — {title}" if perf else f"{i}. {title}")

    await cb.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=ui.playlist_tracks_list_kb(pl_id, tracks, page),
    )


@router.callback_query(F.data.startswith("pl:rm:"))
async def cb_pl_rm_track(cb: CallbackQuery) -> None:
    """Удалить трек из плейлиста по префиксу хеша."""
    await cb.answer()
    parts      = cb.data.split(":")
    pl_id      = int(parts[2])
    hash_prefix = parts[3]
    user_id    = await _ensure_user(cb.from_user)

    tracks = await pl.get_tracks(pl_id)
    full_hash = next(
        (t["track_hash"] for t in tracks if t["track_hash"].startswith(hash_prefix)), None
    )
    if not full_hash:
        await cb.message.answer("❌ Трек не найден.")
        return

    ok = await pl.remove_track(pl_id, user_id, full_hash)
    if not ok:
        await cb.message.answer("❌ Не удалось удалить трек.")
        return

    # Обновляем список
    tracks = await pl.get_tracks(pl_id)
    playlist = await pl.get(pl_id, user_id)
    if not tracks:
        await cb.message.edit_text(
            f"🎼 <b>{playlist['name']}</b>\n\n✅ Трек удалён.\n<i>Плейлист пустой.</i>",
            parse_mode="HTML",
            reply_markup=ui.playlist_detail_kb(pl_id, 0),
        )
    else:
        per_page = 8
        total_pages = (len(tracks) - 1) // per_page + 1
        lines = [f"🎼 <b>{playlist['name']}</b>  ({len(tracks)} тр.)", "✅ Трек удалён\n"]
        for i, t in enumerate(tracks[:8], 1):
            perf  = t.get("performer", "")
            title = t.get("title", "?")
            lines.append(f"{i}. {perf} — {title}" if perf else f"{i}. {title}")
        await cb.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=ui.playlist_tracks_list_kb(pl_id, tracks, 0),
        )


@router.callback_query(F.data.startswith("pl:delete:"))
async def cb_pl_delete(cb: CallbackQuery) -> None:
    await cb.answer()
    pl_id = int(cb.data.split(":")[2])
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
    await cb.message.edit_text("✏ Введите новое название:", reply_markup=ui.cancel_search_kb())


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
    """Воспроизводит плейлист: отправляет треки по одному (с подкачкой отсутствующих)."""
    await cb.answer("⏳ Загружаю плейлист...")
    pl_id   = int(cb.data.split(":")[2])
    user_id = await _ensure_user(cb.from_user)
    tracks  = await pl.get_tracks(pl_id)

    if not tracks:
        await cb.message.answer("ℹ️ Плейлист пустой.")
        return

    from config import CACHE_DIR
    sent = 0
    limit = min(len(tracks), 10)
    await cb.message.answer(f"▶ Отправляю плейлист ({limit} из {len(tracks)} треков)...")

    for t in tracks[:limit]:
        mp3_path = Path(CACHE_DIR) / f"{t['track_hash']}.mp3"
        if not mp3_path.exists():
            # Подкачиваем трек
            q = f"{t.get('performer','')} {t.get('title','')}".strip()
            if not q:
                continue
            track = await search_and_download(q)
            if not track:
                continue
            mp3_path = Path(track["file_path"])

        try:
            audio_file = FSInputFile(str(mp3_path))
            await cb.message.answer_audio(
                audio=audio_file,
                title=t.get("title", ""),
                performer=t.get("performer", ""),
                duration=t.get("duration", 0),
                reply_markup=ui.track_actions_kb(t["track_hash"]),
            )
            sent += 1
            await asyncio.sleep(0.7)
        except Exception as e:
            log.warning("Ошибка отправки трека плейлиста: %s", e)

    if sent == 0:
        await cb.message.answer("❌ Не удалось отправить треки из плейлиста.")


# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text("⚙ <b>Настройки</b>", parse_mode="HTML", reply_markup=ui.settings_kb())


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
# ПОИСК ВНЕ МЕНЮ
# ─────────────────────────────────────────────

@router.message(F.text, ~F.text.startswith("/"))
async def handle_freetext_search(message: Message, state: FSMContext) -> None:
    """Любой текст вне FSM → поиск треков."""
    current_state = await state.get_state()
    if current_state is not None:
        return
    query = message.text.strip()
    if query:
        await _ensure_user(message.from_user)
        await _do_search(message, state, query)
