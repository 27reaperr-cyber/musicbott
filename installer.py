"""
installer.py — Автоустановка зависимостей и FFmpeg.
Запускается до импорта любых внешних библиотек.
"""

import os
import sys
import subprocess
import platform
import shutil
import tarfile
import zipfile
import stat
import logging

log = logging.getLogger("installer")

# ─────────────────────────────────────────────
# 1. PYTHON ЗАВИСИМОСТИ
# ─────────────────────────────────────────────

REQUIRED_PACKAGES = [
    "aiogram>=3.4.1",
    "yt-dlp>=2024.1.1",
    "aiohttp>=3.9.0",
    "aiosqlite>=0.20.0",
    "python-dotenv>=1.0.0",
]

def ensure_packages() -> None:
    """Проверяет и устанавливает отсутствующие pip-пакеты."""
    missing = []
    checks = {
        "aiogram":       "aiogram",
        "yt_dlp":        "yt-dlp>=2024.1.1",
        "aiohttp":       "aiohttp>=3.9.0",
        "aiosqlite":     "aiosqlite>=0.20.0",
        "dotenv":        "python-dotenv>=1.0.0",
    }
    for module, pkg in checks.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[installer] Устанавливаю пакеты: {missing}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade"] + missing
        )
        print("[installer] Пакеты установлены.")
    else:
        print("[installer] Все Python-пакеты уже установлены.")


# ─────────────────────────────────────────────
# 2. FFMPEG
# ─────────────────────────────────────────────

FFMPEG_DIR = os.path.join(os.path.dirname(__file__), "ffmpeg_bin")

# Статические сборки
FFMPEG_URLS = {
    "Linux": (
        "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "tar.xz",
    ),
    "Windows": (
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "zip",
    ),
    "Darwin": (
        "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
        "zip",
    ),
}


def _chmod_x(path: str) -> None:
    current = os.stat(path).st_mode
    os.chmod(path, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _find_binary(root: str, name: str) -> str | None:
    """Рекурсивно ищет исполняемый файл по имени."""
    for dirpath, _, files in os.walk(root):
        for f in files:
            base = f.lower()
            if base == name or base == f"{name}.exe":
                return os.path.join(dirpath, f)
    return None


async def _download_ffmpeg_async(url: str, dest: str) -> None:
    """Скачивает файл через aiohttp (стриминг, без RAM-переполнения)."""
    import aiohttp  # уже установлен к этому моменту
    print(f"[installer] Скачиваю FFmpeg: {url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 256):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"\r[installer] Загрузка FFmpeg... {pct}%", end="", flush=True)
    print()


def _extract(archive: str, fmt: str, target_dir: str) -> None:
    os.makedirs(target_dir, exist_ok=True)
    if fmt == "tar.xz":
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(target_dir)
    elif fmt == "zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(target_dir)
    else:
        raise ValueError(f"Неизвестный формат: {fmt}")


async def ensure_ffmpeg() -> None:
    """Проверяет FFmpeg, при отсутствии — скачивает статическую сборку."""
    # Сначала проверяем системный PATH
    if shutil.which("ffmpeg"):
        print("[installer] FFmpeg найден в системном PATH.")
        return

    # Проверяем наш локальный ffmpeg_bin
    local_ffmpeg = _find_binary(FFMPEG_DIR, "ffmpeg")
    if local_ffmpeg:
        print(f"[installer] Используем локальный FFmpeg: {local_ffmpeg}")
        _inject_ffmpeg_to_path()
        return

    # Нужно скачать
    system = platform.system()
    if system not in FFMPEG_URLS:
        raise RuntimeError(f"Неподдерживаемая ОС для автоустановки FFmpeg: {system}")

    url, fmt = FFMPEG_URLS[system]
    archive_path = os.path.join(FFMPEG_DIR, f"ffmpeg_archive.{fmt}")
    extract_dir = os.path.join(FFMPEG_DIR, "extracted")

    os.makedirs(FFMPEG_DIR, exist_ok=True)

    try:
        await _download_ffmpeg_async(url, archive_path)
    except Exception as e:
        print(f"[installer] Не удалось скачать FFmpeg: {e}")
        print("[installer] ⚠ Конвертация аудио будет недоступна.")
        return

    print("[installer] Распаковываю FFmpeg...")
    _extract(archive_path, fmt, extract_dir)
    os.remove(archive_path)

    # Ищем бинарник
    local_ffmpeg = _find_binary(extract_dir, "ffmpeg")
    if not local_ffmpeg:
        print("[installer] ⚠ Бинарник ffmpeg не найден после распаковки.")
        return

    # Копируем в ffmpeg_bin/
    dest_name = "ffmpeg" + (".exe" if system == "Windows" else "")
    final_path = os.path.join(FFMPEG_DIR, dest_name)
    shutil.copy2(local_ffmpeg, final_path)

    # Копируем ffprobe если есть
    local_ffprobe = _find_binary(extract_dir, "ffprobe")
    if local_ffprobe:
        fp_dest = os.path.join(FFMPEG_DIR, "ffprobe" + (".exe" if system == "Windows" else ""))
        shutil.copy2(local_ffprobe, fp_dest)
        _chmod_x(fp_dest)

    # Убираем мусор
    shutil.rmtree(extract_dir, ignore_errors=True)

    _chmod_x(final_path)
    _inject_ffmpeg_to_path()
    print(f"[installer] ✅ FFmpeg установлен: {final_path}")


def _inject_ffmpeg_to_path() -> None:
    """Добавляет ffmpeg_bin в PATH текущего процесса."""
    abs_dir = os.path.abspath(FFMPEG_DIR)
    current_path = os.environ.get("PATH", "")
    if abs_dir not in current_path:
        os.environ["PATH"] = abs_dir + os.pathsep + current_path


# ─────────────────────────────────────────────
# 3. ТОЧКА ВХОДА
# ─────────────────────────────────────────────

async def run_installer() -> None:
    """Полная автоустановка: пакеты + FFmpeg."""
    ensure_packages()
    await ensure_ffmpeg()
