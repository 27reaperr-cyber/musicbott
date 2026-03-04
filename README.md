# 🎵 Telegram Music Bot

Production-ready Telegram бот для поиска и скачивания музыки.
Разработан для BotHost.ru — не требует sudo, всё устанавливается автоматически.

---

## 🚀 Быстрый старт

### 1. Клонировать / скачать проект

```bash
git clone <repo> tgmusicbot
cd tgmusicbot
```

### 2. Создать .env

```bash
cp .env.example .env
```

Откройте `.env` и вставьте токен бота (получить у [@BotFather](https://t.me/BotFather)):

```
BOT_TOKEN=1234567890:ABC-DEFxxxxxxxxxxxxxxxxxx
LOG_LEVEL=INFO
```

### 3. Запустить

```bash
python main.py
```

**Всё остальное происходит автоматически:**
- Устанавливаются pip-зависимости
- Скачивается и распаковывается FFmpeg
- Создаётся база данных SQLite
- Очищается устаревший кеш
- Бот начинает принимать апдейты

---

## ⚙ Требования

| Компонент | Версия    |
|-----------|-----------|
| Python    | 3.11+     |
| ОС        | Linux / Windows / macOS |
| RAM       | ≥ 256 МБ  |
| Диск      | ≥ 500 МБ  |

> pip-пакеты и FFmpeg устанавливаются автоматически, sudo не нужен.

---

## 📁 Структура проекта

```
tgmusicbot/
├── main.py          # Точка входа, запуск бота
├── installer.py     # Автоустановка зависимостей и FFmpeg
├── config.py        # Конфигурация (env, константы)
├── database.py      # SQLite схема + CRUD
├── menu_router.py   # Все хендлеры, FSM, логика меню
├── ui.py            # Клавиатуры и шаблоны сообщений
├── downloader.py    # Поиск и скачивание через yt-dlp
├── wave_engine.py   # Алгоритм «Моя волна»
├── playlists.py     # Управление плейлистами
├── top_engine.py    # Глобальный топ и тренды
├── stats.py         # Пользовательская статистика
├── history.py       # История прослушиваний
├── rate_limiter.py  # Rate limiting + flood detection
├── anti_abuse.py    # Middleware антиспама для aiogram
├── cleaner.py       # Очистка кеша + VACUUM SQLite
├── requirements.txt
├── .env.example
├── cache/           # MP3-файлы (TTL 24ч)
├── logs/            # Ротируемые логи (bot.log)
└── ffmpeg_bin/      # Локальная копия FFmpeg
```

---

## 🔧 Как работает автоустановка

### Шаг 1: Python-зависимости

При запуске `main.py` до всех импортов вызывается `installer.ensure_packages()`.

Функция пробует `import` каждого модуля и при `ImportError` запускает:

```python
subprocess.check_call([
    sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
    "aiogram>=3.4.1", "yt-dlp>=2024.1.1", ...
])
```

Это **не требует sudo** — пакеты устанавливаются в пользовательское окружение Python.

### Шаг 2: FFmpeg

```
shutil.which("ffmpeg")  →  найден → всё ок
                        ↓  не найден
platform.system()
  "Linux"   → johnvansickle.com (статический tar.xz, amd64)
  "Windows" → gyan.dev (zip с essentials)
  "Darwin"  → evermeet.cx (zip)
        ↓
aiohttp стриминг → ./ffmpeg_bin/ffmpeg_archive.*
        ↓
tarfile / zipfile.extractall()
        ↓
_find_binary()  →  shutil.copy2() → ./ffmpeg_bin/ffmpeg
        ↓
chmod +x
        ↓
os.environ["PATH"] = "./ffmpeg_bin:" + PATH
```

Всё происходит внутри папки проекта, без прав root.

---

## 🎛 Архитектура

### Основной поток данных

```
Telegram → aiogram Dispatcher
              ↓
    AntiAbuseMiddleware (rate limit + flood)
              ↓
    menu_router.py (handlers + FSM)
         ↙          ↘
  downloader.py    database.py
  (yt-dlp, FFmpeg) (aiosqlite)
         ↘          ↙
    cache/*.mp3   history/playlists/tracks
```

### Компоненты

| Модуль | Ответственность |
|--------|----------------|
| `installer.py` | Автоустановка pip + FFmpeg (до импортов) |
| `config.py` | Единый источник конфигурации |
| `database.py` | WAL-SQLite, схема, все CRUD-операции, индексы |
| `downloader.py` | yt-dlp search → validate → download → mp3 кеш |
| `wave_engine.py` | 70% похожие + 20% тренд + 10% случайные |
| `top_engine.py` | Глобальный топ (≥1000 уникальных) + trending 24ч |
| `rate_limiter.py` | In-memory: 1 req/5s, flood mute, error block |
| `anti_abuse.py` | aiogram middleware над rate_limiter |
| `cleaner.py` | Фоновая задача: чистка кеша + VACUUM |
| `menu_router.py` | Все хендлеры, FSM поиска и плейлистов |
| `ui.py` | InlineKeyboardBuilder — все клавиатуры |

### База данных (SQLite WAL)

```sql
users          — telegram_id, username, created_at
tracks         — track_hash (SHA256), title, performer, total_requests, unique_users
history        — user_id → track_hash + timestamp
playlists      — user_id, name
playlist_tracks — playlist_id → track_hash (уникальная пара)
```

Все таблицы имеют индексы на внешние ключи и часто используемые поля.

### Кеш MP3

- Файл: `cache/<sha256(query)>.mp3`
- TTL: 24 часа (проверяется по mtime)
- При старте + каждые 6 часов — очистка устаревших файлов
- `asyncio.Semaphore(3)` — не более 3 параллельных загрузок

### Приватность в топе

- Текстовые запросы **не хранятся** публично
- Считаются только `SHA256(query.lower().strip())`
- В глобальный топ попадают треки с `unique_users >= 1000`

---

## 🛡 Антиспам

| Механизм | Параметр |
|----------|----------|
| Rate limit | 1 запрос / 5 секунд |
| Flood detection | >10 за минуту → мут 10 мин |
| Error block | 5 ошибок подряд → временный бан |
| Download semaphore | max 3 параллельных загрузки |
| Exponential backoff | при ошибках yt-dlp (2→4→8s) |

---

## 📝 Логирование

Логи пишутся в `logs/bot.log` с ротацией (5 МБ × 3 файла) и одновременно в stdout.

Формат:
```
2024-01-15 12:34:56  INFO      downloader           Кеш-хит: a1b2c3d4
2024-01-15 12:34:58  WARNING   rate_limiter         Флуд от 123456789 — мут на 10 мин.
```

---

## ⚡ Производительность

- **Без блокировки event loop** — все I/O операции через `run_in_executor`
- **Стриминг** — yt-dlp и aiohttp читают/пишут чанками (256 КБ)
- **WAL-режим** SQLite — параллельные читатели не блокируют писателей
- **MemoryStorage** FSM — состояния в RAM (для масштабирования замените на Redis)

---

## 🔄 Обновление

```bash
# Обновить yt-dlp (часто выходят обновления для YouTube)
python -m pip install --upgrade yt-dlp

# Перезапустить бот
python main.py
```
