"""Скачивает картинки упражнений из каталога в папку images/.

Запуск из корня проекта:  python -m scripts.download_images
"""

import ssl
import sys
import urllib.request
from pathlib import Path

from data.exercises import CATALOG

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # certifi ставится вместе с aiogram, но на всякий случай
    SSL_CONTEXT = ssl.create_default_context()

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


def main() -> int:
    IMAGES_DIR.mkdir(exist_ok=True)
    failed = []
    for ex in CATALOG.values():
        if not ex.image:
            continue
        target = IMAGES_DIR / f"{ex.image}.jpg"
        if target.exists():
            continue
        try:
            with urllib.request.urlopen(ex.image_url, timeout=30, context=SSL_CONTEXT) as resp:
                target.write_bytes(resp.read())
            print(f"ok   {ex.image}")
        except Exception as e:  # noqa: BLE001
            failed.append(ex.image)
            print(f"FAIL {ex.image}: {e}")
    print(f"\nГотово. Ошибок: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
