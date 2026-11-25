"""Parser for osu! stable replay files (.osr)."""

import lzma
import struct
from dataclasses import dataclass, field

MODS = {
    1 << 0: "NF", 1 << 1: "EZ", 1 << 3: "HD", 1 << 4: "HR", 1 << 5: "SD",
    1 << 6: "DT", 1 << 8: "HT", 1 << 9: "NC", 1 << 10: "FL", 1 << 14: "PF",
    1 << 20: "FI", 1 << 21: "RD", 1 << 30: "MR",
    1 << 15: "4K", 1 << 16: "5K", 1 << 17: "6K", 1 << 18: "7K", 1 << 19: "8K",
    1 << 24: "9K", 1 << 26: "1K", 1 << 27: "3K", 1 << 28: "2K",
}

MOD_EZ, MOD_HR, MOD_DT, MOD_HT, MOD_NC, MOD_MR = 2, 16, 64, 256, 512, 1 << 30


@dataclass
class Replay:
    mode: int
    version: int
    beatmap_md5: str
    player: str
    count_300: int
    count_100: int
    count_50: int
    count_geki: int
    count_katu: int
    count_miss: int
    score: int
    max_combo: int
    perfect: bool
    mods: int
    timestamp: int
    # list of (absolute_time_ms, key_bitmask)
    frames: list = field(default_factory=list)

    @property
    def rate(self) -> float:
        if self.mods & (MOD_DT | MOD_NC):
            return 1.5
        if self.mods & MOD_HT:
            return 0.75
        return 1.0

    @property
    def mod_string(self) -> str:
        names = []
        for bit, name in MODS.items():
            if self.mods & bit:
                names.append(name)
        if "NC" in names and "DT" in names:
            names.remove("DT")
        if "PF" in names and "SD" in names:
            names.remove("SD")
        return "".join(names)


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        value = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def byte(self): return self._unpack("<B")
    def short(self): return self._unpack("<H")
    def int(self): return self._unpack("<i")
    def long(self): return self._unpack("<q")

    def uleb128(self) -> int:
        result = shift = 0
        while True:
            b = self.byte()
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7

    def string(self) -> str:
        marker = self.byte()
        if marker == 0x00:
            return ""
        if marker != 0x0B:
            raise ValueError(f"invalid string marker {marker:#x} at {self.pos - 1}")
        length = self.uleb128()
        raw = self.data[self.pos:self.pos + length]
        self.pos += length
        return raw.decode("utf-8", errors="replace")

    def raw(self, n: int) -> bytes:
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk


def parse_replay(path) -> Replay:
    with open(path, "rb") as fh:
        r = _Reader(fh.read())

    rep = Replay(
        mode=r.byte(), version=r.int(), beatmap_md5=r.string(), player=r.string(),
        **{"count_300": 0, "count_100": 0, "count_50": 0, "count_geki": 0,
           "count_katu": 0, "count_miss": 0, "score": 0, "max_combo": 0,
           "perfect": False, "mods": 0, "timestamp": 0},
    )
    r.string()  # replay md5
    rep.count_300 = r.short()
    rep.count_100 = r.short()
    rep.count_50 = r.short()
    rep.count_geki = r.short()
    rep.count_katu = r.short()
    rep.count_miss = r.short()
    rep.score = r.int()
    rep.max_combo = r.short()
    rep.perfect = bool(r.byte())
    rep.mods = r.int()
    r.string()  # life bar graph
    rep.timestamp = r.long()
    length = r.int()
    compressed = r.raw(length)

    text = lzma.decompress(compressed, format=lzma.FORMAT_ALONE).decode("ascii")
    t = 0
    frames = []
    for chunk in text.split(","):
        if not chunk:
            continue
        parts = chunk.split("|")
        if len(parts) < 4:
            continue
        delta = int(parts[0])
        if delta == -12345:  # RNG seed frame
            continue
        t += delta
        keys = int(float(parts[1]))
        frames.append((t, keys))
    rep.frames = frames
    return rep
