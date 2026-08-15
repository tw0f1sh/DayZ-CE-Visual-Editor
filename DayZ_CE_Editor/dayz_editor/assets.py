from __future__ import annotations

import os
import struct
import urllib.request
from pathlib import Path
from typing import Callable


BASE_RAW = "https://raw.githubusercontent.com/BohemiaInteractive/DayZ-Central-Economy/master/CETool/ChernarusPlus"

OFFICIAL_ASSETS: dict[str, str] = {
    "Base map": "map.png",
    "Tier: Tier1": "layers/valueFlg_Tier1.tga",
    "Tier: Tier2": "layers/valueFlg_Tier2.tga",
    "Tier: Tier3": "layers/valueFlg_Tier3.tga",
    "Tier: Tier4": "layers/valueFlg_Tier4.tga",
    "Tier: Unique": "layers/valueFlg_Unique.tga",
    "Usage: Coast": "layers/usgFlg_Def-Coast.tga",
    "Usage: Farm": "layers/usgFlg_Def-Farm.tga",
    "Usage: Firefighter": "layers/usgFlg_Def-Firefighter.tga",
    "Usage: Hunting": "layers/usgFlg_Def-Hunting.tga",
    "Usage: Industrial": "layers/usgFlg_Def-Industrial.tga",
    "Usage: Medic": "layers/usgFlg_Def-Medic.tga",
    "Usage: Military": "layers/usgFlg_Def-Military.tga",
    "Usage: Office": "layers/usgFlg_Def-Office.tga",
    "Usage: Police": "layers/usgFlg_Def-Police.tga",
    "Usage: Prison": "layers/usgFlg_Def-Prison.tga",
    "Usage: School": "layers/usgFlg_Def-School.tga",
    "Usage: Town": "layers/usgFlg_Def-Town.tga",
    "Usage: Village": "layers/usgFlg_Def-Village.tga",
}


def cache_root() -> Path:
    return Path.home() / ".dayz_ce_visual_editor" / "CETool" / "ChernarusPlus"


def local_asset_paths() -> dict[str, Path]:
    root = cache_root()
    return {label: root / rel for label, rel in OFFICIAL_ASSETS.items()}


def _looks_valid_asset(path: Path) -> bool:
    """Cheap cache validation without fully decoding the potentially quirky TGA."""
    try:
        size = path.stat().st_size
        if size <= 18:
            return False
        if path.suffix.lower() != ".tga":
            return size > 1024
        header = path.read_bytes()[:18]
        if len(header) != 18:
            return False
        image_type = header[2]
        width, height = struct.unpack_from("<HH", header, 12)
        depth = header[16]
        return image_type in {1, 2, 3, 9, 10, 11} and width > 0 and height > 0 and depth in {8, 16, 24, 32}
    except (OSError, ValueError, struct.error):
        return False


def download_official_assets(
    progress: Callable[[int, int, str], None] | None = None,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Download/refresh BI CETool assets atomically.

    ``force=True`` intentionally replaces an older cache. This matters for users
    who already cached a truncated TGA in an earlier editor version.
    """
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    items = list(OFFICIAL_ASSETS.items())
    for idx, (label, rel) in enumerate(items, start=1):
        dest = root / rel
        if force or not _looks_valid_asset(dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = f"{BASE_RAW}/{rel}"
            req = urllib.request.Request(url, headers={"User-Agent": "DayZ-CE-Visual-Editor/0.4"})
            temp = dest.with_suffix(dest.suffix + ".part")
            try:
                with urllib.request.urlopen(req, timeout=60) as response, temp.open("wb") as f:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                if not _looks_valid_asset(temp):
                    raise OSError(f"Heruntergeladene CETool-Datei ist ungültig oder unvollständig: {rel}")
                os.replace(temp, dest)
            finally:
                if temp.exists():
                    try:
                        temp.unlink()
                    except OSError:
                        pass
        if progress:
            progress(idx, len(items), label)
    return local_asset_paths()
