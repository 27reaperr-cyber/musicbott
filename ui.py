"""
ui.py — Все клавиатуры и шаблоны сообщений.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ─────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────────

MAIN_MENU_TEXT = (
    "🎵 <b>Музыкальный бот</b>\n\n"
    "Привет! Я помогу найти и скачать любую музыку. "
    "Выбери раздел ниже 👇"
)


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Найти трек",   callback_data="menu:search")
    kb.button(text="🌊 Моя волна",    callback_data="menu:wave")
    kb.button(text="🔥 Топ",          callback_data="menu:top")
    kb.button(text="🎼 Плейлисты",    callback_data="menu:playlists")
    kb.button(text="📊 Статистика",   callback_data="menu:stats")
    kb.button(text="🕘 История",      callback_data="menu:history")
    kb.button(text="⚙ Настройки",     callback_data="menu:settings")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def back_to_main_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    return kb.as_markup()


# ─────────────────────────────────────────────
# ТОП
# ─────────────────────────────────────────────

def top_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 Глобальный топ",    callback_data="top:global")
    kb.button(text="🔥 Trending 24ч",      callback_data="top:trending")
    kb.button(text="🏠 Главное меню",      callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def top_tracks_kb(tracks: list[dict], prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, t in enumerate(tracks, 1):
        title = (t.get("title") or "?")[:30]
        kb.button(
            text=f"{i}. {title}",
            callback_data=f"{prefix}:{t['track_hash']}",
        )
    kb.button(text="◀ Назад", callback_data="menu:top")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# ИСТОРИЯ
# ─────────────────────────────────────────────

def history_kb(tracks: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tracks[:10]:
        title = (t.get("title") or "?")[:28]
        perf = (t.get("performer") or "")[:15]
        label = f"{perf} — {title}" if perf else title
        kb.button(
            text=label,
            callback_data=f"dl_hash:{t['track_hash']}",
        )
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# ПЛЕЙЛИСТЫ
# ─────────────────────────────────────────────

def playlists_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать плейлист",  callback_data="pl:create")
    kb.button(text="📋 Мои плейлисты",    callback_data="pl:list")
    kb.button(text="🏠 Главное меню",      callback_data="menu:main")
    kb.adjust(1)
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


def playlist_detail_kb(pl_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="▶ Воспроизвести",    callback_data=f"pl:play:{pl_id}")
    kb.button(text="✏ Переименовать",    callback_data=f"pl:rename:{pl_id}")
    kb.button(text="🗑 Удалить плейлист", callback_data=f"pl:delete:{pl_id}")
    kb.button(text="◀ Мои плейлисты",   callback_data="pl:list")
    kb.button(text="🏠 Главное меню",    callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def playlist_tracks_kb(pl_id: int, tracks: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tracks[:20]:
        title = (t.get("title") or "?")[:28]
        kb.button(
            text=f"❌ {title}",
            callback_data=f"pl:rmtrack:{pl_id}:{t['track_hash'][:16]}",
        )
    kb.button(text="◀ Назад", callback_data=f"pl:open:{pl_id}")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

def settings_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Очистить историю",  callback_data="settings:clear_history")
    kb.button(text="🏠 Главное меню",      callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# МОЯ ВОЛНА
# ─────────────────────────────────────────────

def wave_results_kb(tracks: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tracks:
        title = (t.get("title") or "?")[:30]
        kb.button(text=f"🎵 {title}", callback_data=f"dl_hash:{t['track_hash']}")
    kb.button(text="🔄 Обновить волну", callback_data="menu:wave")
    kb.button(text="🏠 Главное меню",   callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


# ─────────────────────────────────────────────
# ПОИСК
# ─────────────────────────────────────────────

def cancel_search_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="menu:main")
    return kb.as_markup()


# ─────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ
# ─────────────────────────────────────────────

def confirm_kb(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=yes_data)
    kb.button(text="❌ Нет", callback_data=no_data)
    kb.adjust(2)
    return kb.as_markup()
