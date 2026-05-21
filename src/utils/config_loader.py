import json
from pathlib import Path

_root = Path(__file__).parent.parent.parent  # C:\VisiPick
_config_path = _root / "config" / "config.json"

with open(_config_path, "r", encoding="utf-8-sig") as f:
    config = json.load(f)
