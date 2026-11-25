"""Parser for osu! beatmap files (.osu), focused on osu!mania."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Note:
    column: int
    time: int
    end: int | None = None  # set for hold notes

    @property
    def is_hold(self) -> bool:
        return self.end is not None


@dataclass
class Beatmap:
    path: Path
    mode: int = 0
    audio_file: str = ""
    title: str = ""
    artist: str = ""
    version: str = ""
    creator: str = ""
    keys: int = 4
    od: float = 5.0
    hp: float = 5.0
    background: str | None = None
    notes: list = field(default_factory=list)
    timing_points: list = field(default_factory=list)  # (time, beat_length) of uninherited points

    @property
    def folder(self) -> Path:
        return self.path.parent

    @property
    def audio_path(self) -> Path:
        return self.folder / self.audio_file

    @property
    def background_path(self) -> Path | None:
        if not self.background:
            return None
        return self.folder / self.background


def parse_beatmap(path) -> Beatmap:
    path = Path(path)
    bm = Beatmap(path=path)
    section = None
    raw_objects = []

    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue

            if section in ("General", "Metadata", "Difficulty"):
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key, value = key.strip(), value.strip()
                if key == "Mode":
                    bm.mode = int(value)
                elif key == "AudioFilename":
                    bm.audio_file = value
                elif key == "Title":
                    bm.title = value
                elif key == "Artist":
                    bm.artist = value
                elif key == "Version":
                    bm.version = value
                elif key == "Creator":
                    bm.creator = value
                elif key == "CircleSize":
                    bm.keys = int(round(float(value)))
                elif key == "OverallDifficulty":
                    bm.od = float(value)
                elif key == "HPDrainRate":
                    bm.hp = float(value)

            elif section == "Events":
                parts = [p.strip() for p in line.split(",")]
                # Background: 0,0,"file.jpg",x,y
                if bm.background is None and len(parts) >= 3 and parts[0] == "0" and parts[1] == "0":
                    bm.background = parts[2].strip('"')

            elif section == "TimingPoints":
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        t, beat = float(parts[0]), float(parts[1])
                    except ValueError:
                        continue
                    uninherited = parts[6].strip() == "1" if len(parts) > 6 else beat > 0
                    if uninherited and beat > 0:
                        bm.timing_points.append((t, beat))

            elif section == "HitObjects":
                raw_objects.append(line)

    for line in raw_objects:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        x = int(float(parts[0]))
        time = int(float(parts[2]))
        obj_type = int(parts[3])
        column = min(bm.keys - 1, max(0, int(x * bm.keys / 512)))
        end = None
        if obj_type & 128 and len(parts) >= 6:
            end = int(float(parts[5].split(":")[0]))
            if end <= time:
                end = None
        bm.notes.append(Note(column=column, time=time, end=end))

    bm.notes.sort(key=lambda n: (n.time, n.column))
    bm.timing_points.sort()
    return bm
