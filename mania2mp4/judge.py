"""Re-simulate osu!mania (stable, ScoreV1) judgements from replay key presses."""

from dataclasses import dataclass

from .osr import MOD_EZ, MOD_HR

# Judgement ids
MAX, J300, J200, J100, J50, MISS = 0, 1, 2, 3, 4, 5
NAMES = ["MAX", "300", "200", "100", "50", "MISS"]
ACC_WEIGHT = [300, 300, 200, 100, 50, 0]


@dataclass
class Windows:
    max: float
    w300: float
    w200: float
    w100: float
    w50: float
    miss: float

    def judge(self, offset: float) -> int:
        a = abs(offset)
        if a <= self.max:
            return MAX
        if a <= self.w300:
            return J300
        if a <= self.w200:
            return J200
        if a <= self.w100:
            return J100
        if a <= self.w50:
            return J50
        return MISS


def hit_windows(od: float, mods: int) -> Windows:
    w = [16.0, 64 - 3 * od, 97 - 3 * od, 127 - 3 * od, 151 - 3 * od, 188 - 3 * od]
    if mods & MOD_HR:
        w = [x / 1.4 for x in w]
    elif mods & MOD_EZ:
        w = [x * 1.4 for x in w]
    w = [float(int(x)) for x in w]
    return Windows(*w)


@dataclass
class NoteResult:
    judgement: int = MISS
    hit_time: int | None = None      # when the head was pressed
    release_time: int | None = None  # when a hold note was released
    judged_at: int = 0               # when the judgement is shown
    offset: float | None = None      # head offset in ms (negative = early)


def key_events(frames, keys: int):
    """Return per column a list of (press_time, release_time)."""
    presses = [[] for _ in range(keys)]
    down_since = [None] * keys
    prev = 0
    for t, state in frames:
        changed = state ^ prev
        if changed:
            for c in range(keys):
                bit = 1 << c
                if changed & bit:
                    if state & bit:
                        down_since[c] = t
                    elif down_since[c] is not None:
                        presses[c].append((down_since[c], t))
                        down_since[c] = None
        prev = state
    last = frames[-1][0] if frames else 0
    for c in range(keys):
        if down_since[c] is not None:
            presses[c].append((down_since[c], last))
    return presses


def _hold_judgement(win: Windows, head: float, tail: float) -> int:
    h, s = abs(head), abs(head) + abs(tail)
    if h <= win.max * 1.2 and s <= win.max * 2.4:
        return MAX
    if h <= win.w300 * 1.1 and s <= win.w300 * 2.2:
        return J300
    if h <= win.w200 and s <= win.w200 * 2:
        return J200
    if h <= win.w100 and s <= win.w100 * 2:
        return J100
    return J50


def simulate(notes, frames, keys: int, od: float, mods: int):
    win = hit_windows(od, mods)
    presses = key_events(frames, keys)
    results = [NoteResult() for _ in notes]

    by_col = [[] for _ in range(keys)]
    for i, n in enumerate(notes):
        by_col[n.column].append(i)

    for c in range(keys):
        queue = by_col[c]
        qi = 0
        for press, release in presses[c]:
            # Notes that passed their late window without a press are missed.
            while qi < len(queue):
                n = notes[queue[qi]]
                if press - n.time > win.w50:
                    r = results[queue[qi]]
                    r.judgement = MISS
                    r.judged_at = int(n.time + win.w50) if not n.is_hold else n.end
                    qi += 1
                else:
                    break
            if qi >= len(queue):
                break
            idx = queue[qi]
            n = notes[idx]
            offset = press - n.time
            if offset < -win.miss:
                continue  # too early, press is ignored
            r = results[idx]
            r.hit_time = press
            r.offset = offset
            qi += 1
            if abs(offset) > win.w50:
                r.judgement = MISS
                r.judged_at = press if not n.is_hold else n.end
                continue
            if not n.is_hold:
                r.judgement = win.judge(offset)
                r.judged_at = press
                continue
            r.release_time = release
            tail = release - n.end
            if tail < -win.w50:
                r.judgement = J50  # released too early
                r.judged_at = release
            else:
                tail_eff = min(tail, win.w50) if tail > 0 else tail
                r.judgement = _hold_judgement(win, offset, tail_eff)
                r.judged_at = min(release, n.end + int(win.w50)) if tail > 0 else release
                r.judged_at = max(r.judged_at, n.end)

        for idx in queue[qi:]:
            n = notes[idx]
            r = results[idx]
            r.judgement = MISS
            r.judged_at = int(n.time + win.w50) if not n.is_hold else n.end

    return results, win
