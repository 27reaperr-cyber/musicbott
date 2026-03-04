"""
ui.py — Клавиатуры и шаблоны сообщений. Бот: Dreinnify.
"""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ─────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────────

MAIN_MENU_TEXT = (
    "🎵 <b>Dreinnify</b>\n\n"
    "Просто напиши название трека или исполнителя — я найду и отправлю 🎧\n\n"
    "Или выбери раздел:"
)


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌊 Моя волна",   callback_data="menu:wave")
    kb.button(text="🔥 Топ",         callback_data="menu:top")
    kb.button(text="🎼 Плейлисты",   callback_data="menu:playlists")
    kb.button(text="📊 Статистика",  callback_data="menu:stats")
    kb.button(text="🕘 История",     callback_data="menu:history")
    kb.button(text="⚙ Настройки",    callback_data="menu:settings")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def back_to_main_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    return kb.as_markup()


# ─────────────────────────────────────────────
# КНОПКИ ПОД ТРЕКОМ (после отправки аудио)
# ─────────────────────────────────────────────

def track_actions_kb(track_hash: str) -> InlineKeyboardMarkup:
    """
    Кнопки под треком: Speed Up / Slowed / Добавить в плейлист.
    НЕТ кнопки «Главное меню» — она удалит аудио-сообщение.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Speed Up",          callback_data=f"speed:up:{track_hash}")
    kb.button(text="🌊 Slowed",            callback_data=f"speed:slo:{track_hash}")
    kb.button(text="➕ В плейлист",        callback_data=f"addpl:{track_hash}")
    kb.adjust(2, 1)
    return kb.as_markup()


def speed_done_kb(track_hash: str) -> InlineKeyboardMarkup:
    """Кнопки под обработанным треком."""
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ В плейлист", callback_data=f"addpl:{track_hash}")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# ПОИСК
# ─────────────────────────────────────────────

def search_results_kb(tracks: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, t in enumerate(tracks):
        title    = (t.get("title") or "?")[:30]
        dur      = t.get("duration", 0)
        mins, sec = divmod(dur, 60)
        dur_str  = f"{mins}:{sec:02d}" if dur else "?:??"
        kb.button(
            text=f"{i+1}. {title}  [{dur_str}]",
            callback_data=f"pick:{i}",
        )
    kb.button(text="❌ Отмена", callback_data="search:cancel")
    kb.adjust(1)
    return kb.as_markup()


def cancel_search_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="search:cancel")
    return kb.as_markup()


# ─────────────────────────────────────────────
# ТОП
# ─────────────────────────────────────────────

def top_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 Глобальный топ", callback_data="top:global")
    kb.button(text="🏠 Главное меню",   callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def top_tracks_kb(tracks: list[dict], prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, t in enumerate(tracks, 1):
        title = (t.get("title") or "?")[:28]
        perf  = (t.get("performer") or "")[:15]
        label = f"{i}. {perf} — {title}" if perf else f"{i}. {title}"
        kb.button(text=label, callback_data=f"{prefix}:{t['track_hash']}")
    kb.button(text="◀ Назад", callback_data="menu:top")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# ИСТОРИЯ
# ─────────────────────────────────────────────

def history_kb(tracks: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tracks[:15]:
        title = (t.get("title") or "?")[:26]
        perf  = (t.get("performer") or "")[:12]
        label = f"{perf} — {title}" if perf else title
        kb.button(text=label, callback_data=f"dl_hash:{t['track_hash']}")
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# ПЛЕЙЛИСТЫ
# ─────────────────────────────────────────────

def playlists_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать плейлист", callback_data="pl:create")
    kb.button(text="📋 Мои плейлисты",   callback_data="pl:list")
    kb.button(text="🏠 Главное меню",    callback_data="menu:main")
    kb.adjust(2, 1)
    return kb.as_markup()


def playlists_list_kb(playlists: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for pl in playlists:
        kb.button(
            text=f"🎼 {pl['name']} ({pl['track_count']} тр.)",
            callback_data=f"pl:open:{pl['id']}",
        )
    kb.button(text="◀ Назад", callback_data="menu:playlists")
    kb.adjust(1)
    return kb.as_markup()


def playlist_detail_kb(pl_id: int, track_count: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if track_count > 0:
        kb.button(text="▶ Воспроизвести",     callback_data=f"pl:play:{pl_id}")
        kb.button(text="📋 Список треков",     callback_data=f"pl:tracks:{pl_id}")
    kb.button(text="✏ Переименовать",         callback_data=f"pl:rename:{pl_id}")
    kb.button(text="🗑 Удалить плейлист",      callback_data=f"pl:delete:{pl_id}")
    kb.button(text="◀ Мои плейлисты",         callback_data="pl:list")
    kb.button(text="🏠 Главное меню",          callback_data="menu:main")
    kb.adjust(2, 2, 2) if track_count > 0 else kb.adjust(1)
    return kb.as_markup()


def playlist_tracks_list_kb(pl_id: int, tracks: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """Список треков плейлиста с возможностью удаления."""
    kb = InlineKeyboardBuilder()
    per_page = 8
    start = page * per_page
    page_tracks = tracks[start:start + per_page]

    for t in page_tracks:
        title = (t.get("title") or "?")[:24]
        perf  = (t.get("performer") or "")[:10]
        label = f"❌ {perf} — {title}" if perf else f"❌ {title}"
        # используем первые 11 символов хеша (videoId и есть хеш)
        kb.button(
            text=label,
            callback_data=f"pl:rm:{pl_id}:{t['track_hash'][:11]}",
        )

    # Пагинация
    total_pages = (len(tracks) - 1) // per_page + 1 if tracks else 1
    nav = []
    if page > 0:
        nav.append(("◀", f"pl:tracks:{pl_id}:{page-1}"))
    if page < total_pages - 1:
        nav.append(("▶", f"pl:tracks:{pl_id}:{page+1}"))

    kb.adjust(1)
    nav_kb = InlineKeyboardBuilder()
    for label, data in nav:
        nav_kb.button(text=label, callback_data=data)
    nav_kb.button(text="◀ Назад", callback_data=f"pl:open:{pl_id}")
    nav_kb.adjust(len(nav) if nav else 1, 1)

    kb.attach(nav_kb)
    return kb.as_markup()


def select_playlist_for_add_kb(playlists: list[dict], track_hash: str) -> InlineKeyboardMarkup:
    """Выбор плейлиста для добавления трека."""
    kb = InlineKeyboardBuilder()
    for pl in playlists:
        kb.button(
            text=f"🎼 {pl['name']} ({pl['track_count']} тр.)",
            callback_data=f"addpl_c:{pl['id']}:{track_hash}",
        )
    kb.button(text="❌ Отмена", callback_data="addpl_cancel")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# МОЯ ВОЛНА
# ─────────────────────────────────────────────

def wave_results_kb(tracks: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tracks:
        title = (t.get("title") or "?")[:28]
        perf  = (t.get("performer") or "")[:12]
        label = f"🎵 {perf} — {title}" if perf else f"🎵 {title}"
        kb.button(text=label, callback_data=f"dl_hash:{t['track_hash']}")
    kb.button(text="🔄 Обновить волну", callback_data="menu:wave")
    kb.button(text="🏠 Главное меню",   callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

def settings_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Очистить историю", callback_data="settings:clear_history")
    kb.button(text="🏠 Главное меню",     callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ
# ─────────────────────────────────────────────

def confirm_kb(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да",  callback_data=yes_data)
    kb.button(text="❌ Нет", callback_data=no_data)
    kb.adjust(2)
    return kb.as_markup()
