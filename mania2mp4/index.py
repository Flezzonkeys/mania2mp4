"""Find the beatmap that belongs to a replay via its MD5 hash."""

import hashlib
import json
import os
from pathlib import Path

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "mania2mp4"
CACHE_FILE = CACHE_DIR / "beatmap-index.json"

DEFAULT_SONG_DIRS = [
    Path.home() / ".local/share/osu-wine/osu!/Songs",
    Path.home() / "Games/osu-stable/drive_c/users" / os.environ.get("USER", "") / "AppData/Local/osu!/Songs",
]


def default_songs_dir() -> Path | None:
    for d in DEFAULT_SONG_DIRS:
        if d.is_dir():
            return d
    return None


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(CACHE_FILE)


def find_beatmap(md5: str, songs_dir: Path, log=print) -> Path | None:
    """Return the .osu file with the given MD5. Uses a cache keyed by path, size and mtime."""
    cache = _load_cache()
    entries = cache.get(str(songs_dir), {})

    # Fast path: a cached entry that still matches.
    for path, (size, mtime, digest) in entries.items():
        if digest == md5:
            try:
                st = os.stat(path)
            except OSError:
                break
            if st.st_size == size and int(st.st_mtime) == mtime:
                return Path(path)
            break

    log("Indexing beatmaps (only slow the first time)...")
    new_entries = {}
    found = None
    for root, _dirs, files in os.walk(songs_dir):
        for name in files:
            if not name.endswith(".osu"):
                continue
            path = os.path.join(root, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            old = entries.get(path)
            if old and old[0] == st.st_size and old[1] == int(st.st_mtime):
                digest = old[2]
            else:
                with open(path, "rb") as fh:
                    digest = hashlib.md5(fh.read()).hexdigest()
            new_entries[path] = (st.st_size, int(st.st_mtime), digest)
            if digest == md5:
                found = Path(path)

    cache[str(songs_dir)] = new_entries
    _save_cache(cache)
    return found
