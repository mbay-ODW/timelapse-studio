from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image


def make_cc400w_series(folder: Path, start: datetime, count: int, step: timedelta,
                       size=(256, 144), brightness_fn=None) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        t = start + step * i
        v = brightness_fn(t) if brightness_fn else 128
        name = f"CC400W-001-{t:%Y%m%d}-{t:%H%M%S}{i % 10000:04d}-Cam-2-Type-0.jpg"
        p = folder / name
        Image.new("RGB", size, (v, v, v)).save(p, "JPEG", quality=80)
        paths.append(p)
    return paths
