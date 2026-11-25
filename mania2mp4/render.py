"""Scene: draws one video frame of an osu!mania replay."""

import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from . import judge, skins  # noqa: E402
from .inputs import InputOverlay  # noqa: E402

GOLD = skins.GOLD
TEXT = (240, 241, 248)
MUTED = (150, 154, 172)
CARD_BG = (12, 12, 18, 185)
CARD_BORDER = (255, 255, 255, 26)

JUDGE_COLORS = [
    (180, 240, 255),  # MAX
    (255, 214, 92),   # 300
    (120, 230, 120),  # 200
    (90, 160, 255),   # 100
    (170, 170, 180),  # 50
    (255, 80, 80),    # MISS
]


def _font_path(bold: bool) -> str | None:
    if not shutil.which("fc-match"):
        return None
    pattern = "Noto Sans:bold" if bold else "Noto Sans"
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


# Simple striped flags: (orientation, colours)
FLAGS = {
    "de": ("h", [(0, 0, 0), (221, 0, 0), (255, 206, 0)]),
    "at": ("h", [(237, 41, 57), (255, 255, 255), (237, 41, 57)]),
    "nl": ("h", [(174, 28, 40), (255, 255, 255), (33, 70, 139)]),
    "pl": ("h", [(255, 255, 255), (220, 20, 60)]),
    "ua": ("h", [(0, 87, 183), (255, 215, 0)]),
    "ru": ("h", [(255, 255, 255), (0, 57, 166), (213, 43, 30)]),
    "fr": ("v", [(0, 38, 84), (255, 255, 255), (206, 17, 38)]),
    "it": ("v", [(0, 140, 69), (244, 245, 240), (205, 33, 42)]),
    "be": ("v", [(0, 0, 0), (253, 218, 36), (239, 51, 64)]),
}


def draw_flag(surf, code, x, y, h):
    """Draw a small striped flag with a thin outline; returns its width (0 if unknown)."""
    flag = FLAGS.get((code or "").lower())
    if not flag:
        return 0
    orient, cols = flag
    w = int(h * 5 / 3)
    n = len(cols)
    for i, col in enumerate(cols):
        if orient == "h":
            y0, y1 = y + h * i // n, y + h * (i + 1) // n
            pygame.draw.rect(surf, col, (x, y0, w, y1 - y0))
        else:
            x0, x1 = x + w * i // n, x + w * (i + 1) // n
            pygame.draw.rect(surf, col, (x0, y, x1 - x0, h))
    pygame.draw.rect(surf, (110, 112, 128), (x - 1, y - 1, w + 2, h + 2), 1)
    return w


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass
class RenderOptions:
    width: int = 1920
    height: int = 1080
    fps: int = 60
    scroll_ms: float = 450.0
    bg_dim: float = 0.8
    encoder: str = "auto"
    quality: int = 20
    start_ms: float | None = None   # map time to start rendering at (debug/preview)
    duration_s: float | None = None
    results_s: float = 5.0
    offset_ms: float = 0.0          # shifts audio relative to video
    skin: str = "arrow"             # "arrow", "bar", an .osk file, a skin folder or an installed skin name
    colors: str | None = None       # "snap" or "column"; default depends on the skin
    show_inputs: bool = True
    key_labels: list | None = None
    flag: str | None = None         # country code for a small flag next to the player name, e.g. "de"
    ln_end: str = "fade"            # osu! skins: "fade" (soft end), "plain" (simple edge) or "skin" (tail image)


def make_skin(scene, spec: str):
    if spec == "arrow":
        return skins.ArrowSkin(scene)
    if spec == "bar":
        return skins.BarSkin(scene)
    from .osuskin import OsuSkin, SkinError, resolve_skin_dir
    skin_dir = resolve_skin_dir(spec)
    if skin_dir is None:
        print(f"Skin '{spec}' not found, using the arrow skin.", file=sys.stderr)
        return skins.ArrowSkin(scene)
    try:
        return OsuSkin(scene, skin_dir)
    except SkinError as exc:
        print(f"Skin '{skin_dir.name}' cannot be used ({exc}), using the arrow skin.", file=sys.stderr)
        return skins.ArrowSkin(scene)


class Scene:
    def __init__(self, bm, replay, results, win, opts: RenderOptions):
        pygame.font.init()
        self.bm, self.rep, self.res, self.win, self.o = bm, replay, results, win, opts
        W, H = opts.width, opts.height
        self.W, self.H = W, H
        self.u = u = H / 1080.0
        self.keys = bm.keys
        self.colors_by_column = skins.column_colors(self.keys)

        fb, fr = _font_path(True), _font_path(False)
        self.font_bold, self.font_regular = fb, fr
        self.f_combo = pygame.font.Font(fb, int(64 * u))
        self.f_judge = pygame.font.Font(fb, int(46 * u))
        self.f_huge = pygame.font.Font(fb, int(56 * u))
        self.f_big = pygame.font.Font(fb, int(40 * u))
        self.f_title = pygame.font.Font(fb, int(28 * u))
        self.f_med = pygame.font.Font(fb, int(24 * u))
        self.f_small = pygame.font.Font(fr, int(21 * u))
        self.f_small_b = pygame.font.Font(fb, int(21 * u))
        self.f_label = pygame.font.Font(fb, int(15 * u))
        self._text_cache = {}

        self.skin = make_skin(self, opts.skin)
        sk = self.skin
        self.rc_y = sk.rc_y
        self.px_per_ms = sk.rc_y / (opts.scroll_ms * replay.rate)  # map ms -> px

        color_mode = opts.colors or ("snap" if sk.uses_snap else "column")
        if color_mode == "snap":
            self.note_colors = skins.snap_colors(bm.notes, bm.timing_points)
        else:
            self.note_colors = [self.colors_by_column[n.column] for n in bm.notes]

        self._layout()
        self._build_static()
        self._prepare_timeline()
        self.inputs = None
        if opts.show_inputs and self.input_rect.width >= int(220 * u):
            self.inputs = InputOverlay(self, opts.key_labels, self.input_rect)

    # ---------- helpers ----------

    def text(self, font, s, color):
        key = (id(font), s, color)
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 4000:
                self._text_cache.clear()
            surf = font.render(s, True, color)
            self._text_cache[key] = surf
        return surf

    def fit(self, font, s, max_w):
        """Shorten text with an ellipsis until it fits."""
        if font.size(s)[0] <= max_w:
            return s
        while s and font.size(s + "...")[0] > max_w:
            s = s[:-1]
        return s.rstrip() + "..."

    def card(self, surf, rect):
        r = int(14 * self.u)
        box = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(box, CARD_BG, box.get_rect(), border_radius=r)
        pygame.draw.rect(box, CARD_BORDER, box.get_rect(), max(1, int(1.5 * self.u)), border_radius=r)
        surf.blit(box, rect.topleft)

    # ---------- layout and static background ----------

    def _layout(self):
        u, W, H = self.u, self.W, self.H
        sk = self.skin
        self.margin = M = int(36 * u)
        side = sk.field_x
        self.card_w = cw = int(max(0, min(440 * u, side - 2 * M)))
        self.left_x = (side - cw) // 2
        self.right_x = sk.field_x + sk.field_w + (W - sk.field_x - sk.field_w - cw) // 2
        self.pad = int(22 * u)

        self.map_rect = pygame.Rect(self.left_x, M, cw, int(218 * u))
        top = self.map_rect.bottom + int(22 * u)
        self.input_rect = pygame.Rect(self.left_x, top, cw, H - M - top)
        self.stats_rect = pygame.Rect(self.right_x, M, cw, int(500 * u))
        eh = int(150 * u)
        self.error_rect = pygame.Rect(self.right_x, H - M - eh, cw, eh)

    def _load_background(self):
        W, H = self.W, self.H
        path = self.bm.background_path
        if path and path.is_file():
            try:
                from PIL import Image, ImageFilter
                img = Image.open(path).convert("RGB")
                scale = max(W / img.width, H / img.height)
                img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
                left, top = (img.width - W) // 2, (img.height - H) // 2
                img = img.crop((left, top, left + W, top + H))
                img = img.filter(ImageFilter.GaussianBlur(radius=10 * self.u))
                surf = pygame.image.frombytes(img.tobytes(), (W, H), "RGB")
                # Note: per-pixel alpha, set_alpha on opaque 32-bit surfaces only blends blue in SDL here
                dim = pygame.Surface((W, H), pygame.SRCALPHA, 32)
                dim.fill((0, 0, 0, int(255 * self.o.bg_dim)))
                surf.blit(dim, (0, 0))
                return surf
            except Exception as exc:  # noqa: BLE001
                print(f"Background could not be loaded: {exc}", file=sys.stderr)
        surf = pygame.Surface((W, H), 0, 32)
        surf.fill((14, 14, 22))
        return surf

    def _build_static(self):
        u, sk = self.u, self.skin
        bg = self._load_background()

        # Playfield
        field = pygame.Surface((sk.field_w, self.H), pygame.SRCALPHA)
        field.fill((0, 0, 0, sk.field_alpha))
        if sk.column_lines:
            for c in range(1, self.keys):
                x = sk.col_x[c] - sk.field_x
                pygame.draw.line(field, (255, 255, 255, 16), (x, 0), (x, self.H))
        bg.blit(field, (sk.field_x, 0))
        if sk.column_lines:
            edge = (95, 98, 115)
            lw = max(1, int(2 * u))
            pygame.draw.line(bg, edge, (sk.field_x - 1, 0), (sk.field_x - 1, self.H), lw)
            pygame.draw.line(bg, edge, (sk.field_x + sk.field_w, 0), (sk.field_x + sk.field_w, self.H), lw)
        sk.stage(bg)

        if self.card_w > 0:
            self._static_map_card(bg)
            self.card(bg, self.input_rect)
            self.card(bg, self.stats_rect)
            self._static_error_card(bg)

        self.static = pygame.Surface((self.W, self.H), 0, 32)
        self.static.blit(bg, (0, 0))

    def _static_map_card(self, bg):
        u, bm, rep = self.u, self.bm, self.rep
        r = self.map_rect
        self.card(bg, r)
        x, y = r.x + self.pad, r.y + int(18 * u)
        maxw = r.width - 2 * self.pad
        bg.blit(self.text(self.f_label, "NOW PLAYING", MUTED), (x, y))
        y += int(24 * u)
        bg.blit(self.text(self.f_title, self.fit(self.f_title, bm.title, maxw), TEXT), (x, y))
        y += int(38 * u)
        bg.blit(self.text(self.f_small, self.fit(self.f_small, bm.artist, maxw), (205, 208, 222)), (x, y))
        y += int(30 * u)
        diff = self.fit(self.f_small_b, f"[{bm.version}]", maxw)
        bg.blit(self.text(self.f_small_b, diff, GOLD), (x, y))
        y += int(28 * u)
        bg.blit(self.text(self.f_small, self.fit(self.f_small, f"mapped by {bm.creator}", maxw), MUTED), (x, y))
        y += int(36 * u)

        chips = [f"{bm.keys}K", f"OD {bm.od:g}", f"HP {bm.hp:g}"]
        if rep.mod_string:
            chips.append("+" + rep.mod_string)
        cx = x
        for i, chip in enumerate(chips):
            is_mod = chip.startswith("+")
            t = self.text(self.f_label, chip, (20, 20, 26) if is_mod else TEXT)
            cw, ch = t.get_width() + int(18 * u), t.get_height() + int(8 * u)
            pygame.draw.rect(bg, GOLD if is_mod else (60, 62, 78), (cx, y, cw, ch), border_radius=ch // 2)
            bg.blit(t, (cx + int(9 * u), y + int(4 * u)))
            cx += cw + int(8 * u)
        self._player_tag(bg, r.right - self.pad, y + int(2 * u), align_right=True)

    def _player_tag(self, surf, x, y, align_right=False, center=False):
        """'Player: name' followed by the flag. x is the left edge, right edge or centre."""
        u = self.u
        label = self.text(self.f_small, "Player:", MUTED)
        name = self.text(self.f_small_b, self.rep.player, TEXT)
        fh = int(16 * u)
        fw = int(fh * 5 / 3) if (self.o.flag or "").lower() in FLAGS else 0
        gap = int(7 * u)
        total = label.get_width() + gap + name.get_width() + (gap + fw if fw else 0)
        if align_right:
            x -= total
        elif center:
            x -= total // 2
        surf.blit(label, (x, y))
        x += label.get_width() + gap
        surf.blit(name, (x, y))
        x += name.get_width() + gap
        if fw:
            draw_flag(surf, self.o.flag, x, y + (name.get_height() - fh) // 2 + int(1 * u), fh)

    def _static_error_card(self, bg):
        u, r = self.u, self.error_rect
        self.card(bg, r)
        x = r.x + self.pad
        bg.blit(self.text(self.f_label, "HIT ERROR", MUTED), (x, r.y + int(18 * u)))
        self.eb_w = r.width - 2 * self.pad
        self.eb_h = int(10 * u)
        self.eb_cx = r.centerx
        self.eb_y = r.y + int(78 * u)
        self.eb_scale = (self.eb_w / 2) / self.win.w50
        zones = [(self.win.w50, JUDGE_COLORS[4]), (self.win.w100, JUDGE_COLORS[3]),
                 (self.win.w200, JUDGE_COLORS[2]), (self.win.w300, JUDGE_COLORS[1]),
                 (self.win.max, JUDGE_COLORS[0])]
        for w, col in zones:
            half = int(w * self.eb_scale)
            pygame.draw.rect(bg, skins.scale_color(col, 0.45), (self.eb_cx - half, self.eb_y, half * 2, self.eb_h))
        pygame.draw.rect(bg, (255, 255, 255), (self.eb_cx - 1, self.eb_y - int(8 * u), 2, self.eb_h + int(16 * u)))
        early = self.text(self.f_label, "EARLY", MUTED)
        late = self.text(self.f_label, "LATE", MUTED)
        ly = self.eb_y + self.eb_h + int(16 * u)
        bg.blit(early, (x, ly))
        bg.blit(late, (r.right - self.pad - late.get_width(), ly))

    # ---------- timeline ----------

    def _prepare_timeline(self):
        notes, res = self.bm.notes, self.res
        self.events = sorted(range(len(notes)), key=lambda i: res[i].judged_at)
        self.ev_pos = 0
        self.counts = [0] * 6
        self.combo = 0
        self.max_combo = 0
        self.last_judgement = None  # (judgement, time)
        self.recent_offsets = []    # (time, offset, judgement)
        self.off_n = 0
        self.off_sum = 0.0
        self.off_sq = 0.0
        self.last_hit = [-10 ** 9] * self.keys
        self.frame_pos = 0
        self.cur_keys = 0
        self.first_visible = 0
        ends = [(n.end if n.is_hold else n.time) for n in notes]
        self.max_len = max([e - n.time for e, n in zip(ends, notes)] + [0])
        self.map_start = notes[0].time if notes else 0
        self.map_end = max(ends) if ends else 0

    def _advance(self, now):
        res, rate = self.res, self.rep.rate
        while self.ev_pos < len(self.events) and res[self.events[self.ev_pos]].judged_at <= now:
            r = res[self.events[self.ev_pos]]
            j = r.judgement
            self.counts[j] += 1
            if j == judge.MISS:
                self.combo = 0
            else:
                self.combo += 1
                self.max_combo = max(self.max_combo, self.combo)
            self.last_judgement = (j, r.judged_at)
            if r.offset is not None and j != judge.MISS:
                self.recent_offsets.append((r.judged_at, r.offset, j))
                o = r.offset / rate
                self.off_n += 1
                self.off_sum += o
                self.off_sq += o * o
            self.ev_pos += 1
        frames = self.rep.frames
        while self.frame_pos < len(frames) and frames[self.frame_pos][0] <= now:
            t, k = frames[self.frame_pos]
            newly = k & ~self.cur_keys
            for c in range(self.keys):
                if newly & (1 << c):
                    self.last_hit[c] = t
            self.cur_keys = k
            self.frame_pos += 1
        cutoff = now - 4000 * rate
        if self.recent_offsets and self.recent_offsets[0][0] < cutoff:
            self.recent_offsets = [x for x in self.recent_offsets if x[0] >= cutoff]

    def accuracy(self):
        total = sum(self.counts)
        if not total:
            return 100.0
        pts = sum(c * w for c, w in zip(self.counts, judge.ACC_WEIGHT))
        return 100.0 * pts / (300 * total)

    def unstable_rate(self):
        if self.off_n < 2:
            return 0.0, 0.0
        mean = self.off_sum / self.off_n
        var = max(0.0, self.off_sq / self.off_n - mean * mean)
        return 10 * math.sqrt(var), mean

    # ---------- drawing ----------

    def draw(self, surf, now):
        self._advance(now)
        surf.blit(self.static, (0, 0))
        sk = self.skin
        if sk.keys_under_notes:
            sk.receptors(surf, self.cur_keys)
        self._draw_notes(surf, now)
        if not sk.keys_under_notes:
            sk.receptors(surf, self.cur_keys)
        sk.effects(surf, now, self.last_hit, self.rep.rate)
        self._draw_combo_judgement(surf, now)
        if self.card_w > 0:
            self._draw_stats(surf, now)
            self._draw_error_bar(surf, now)
            if self.inputs:
                self.inputs.draw(surf, now)
        self._draw_progress(surf, now)

    def _draw_notes(self, surf, now):
        sk = self.skin
        notes, res, ncol = self.bm.notes, self.res, self.note_colors
        ppm, rc = self.px_per_ms, self.rc_y
        top_time = now + (rc + 200 * self.u) / ppm
        while self.first_visible < len(notes) and notes[self.first_visible].time + self.max_len < now - 2000:
            self.first_visible += 1
        H = self.H
        for i in range(self.first_visible, len(notes)):
            n = notes[i]
            if n.time > top_time:
                break
            r = res[i]
            c = n.column
            cx = sk.col_x[c] + sk.col_w[c] / 2
            if not n.is_hold:
                if r.judgement != judge.MISS and r.hit_time is not None and now >= r.hit_time:
                    continue
                y = rc - (n.time - now) * ppm
                dim = r.judgement == judge.MISS and now > n.time
                spr = sk.note(c, ncol[i], dim)
                if y - spr.get_height() / 2 > H:
                    continue
                surf.blit(spr, (int(cx - spr.get_width() / 2), int(y - spr.get_height() / 2)))
                continue

            held = (r.hit_time is not None and r.judgement != judge.MISS and
                    r.hit_time <= now < (r.release_time or 0))
            released = r.release_time is not None and now >= r.release_time
            if released and r.release_time >= n.end - self.win.w50:
                continue  # finished hold
            if held and now >= n.end:
                continue  # held past the tail
            head_t = n.time
            if held:
                head_t = max(n.time, now)
            elif r.hit_time is not None and now >= r.hit_time and released:
                head_t = max(n.time, r.release_time)
            y_head = rc - (head_t - now) * ppm
            y_tail = rc - (n.end - now) * ppm
            if y_tail - 100 * self.u > H:
                continue
            missed = r.judgement == judge.MISS and now > n.time + self.win.w50
            dead = missed or (released and r.release_time < n.end)
            state = "dead" if dead else ("held" if held else "idle")
            sk.body(surf, c, ncol[i], y_tail, y_head, state)
            sk.tail(surf, c, ncol[i], y_tail, state)
            spr = sk.note(c, ncol[i], dead, hold=True)
            surf.blit(spr, (int(cx - spr.get_width() / 2), int(y_head - spr.get_height() / 2)))

    def _draw_combo_judgement(self, surf, now):
        sk, u, rate = self.skin, self.u, self.rep.rate
        cx = sk.field_x + sk.field_w // 2
        if self.last_judgement:
            j, t = self.last_judgement
            age = (now - t) / rate
            if age < 450:
                spr = sk.judgement(j) or self.text(self.f_judge, judge.NAMES[j], JUDGE_COLORS[j])
                grow = 1.0 + 0.2 * max(0.0, 1 - age / 80)
                if grow > 1.001:
                    spr = pygame.transform.smoothscale(
                        spr, (int(spr.get_width() * grow), int(spr.get_height() * grow)))
                alpha = 255 if age < 300 else int(255 * (1 - (age - 300) / 150))
                spr.set_alpha(alpha)
                surf.blit(spr, (cx - spr.get_width() // 2, sk.judge_y - spr.get_height() // 2))
                spr.set_alpha(None)
        if self.combo >= 2:
            spr = sk.combo(self.combo) or self.text(self.f_combo, str(self.combo), TEXT)
            spr.set_alpha(215)
            surf.blit(spr, (cx - spr.get_width() // 2, sk.combo_y - spr.get_height() // 2))
            spr.set_alpha(None)

    def _draw_stats(self, surf, now):
        u, r = self.u, self.stats_rect
        x, right = r.x + self.pad, r.right - self.pad
        y = r.y + int(18 * u)
        surf.blit(self.text(self.f_label, "ACCURACY", MUTED), (x, y))
        rate = self.rep.rate
        elapsed = (now - self.map_start) / 1000 / rate
        total = (self.map_end - self.map_start) / 1000 / rate
        t = self.text(self.f_label, f"{_fmt_time(min(elapsed, total))} / {_fmt_time(total)}", MUTED)
        surf.blit(t, (right - t.get_width(), y))
        y += int(22 * u)
        surf.blit(self.text(self.f_huge, f"{self.accuracy():.2f}%", TEXT), (x, y))
        y += int(84 * u)

        total_j = max(1, sum(self.counts))
        bar_x = x + int(90 * u)
        bar_w = right - bar_x - int(70 * u)
        for j in range(6):
            surf.blit(self.text(self.f_small_b, judge.NAMES[j], JUDGE_COLORS[j]), (x, y))
            v = self.text(self.f_small_b, str(self.counts[j]), TEXT)
            surf.blit(v, (right - v.get_width(), y))
            by = y + int(11 * u)
            pygame.draw.rect(surf, (40, 42, 54), (bar_x, by, bar_w, int(6 * u)), border_radius=int(3 * u))
            fill = int(bar_w * self.counts[j] / total_j)
            if fill > 0:
                pygame.draw.rect(surf, JUDGE_COLORS[j], (bar_x, by, fill, int(6 * u)), border_radius=int(3 * u))
            y += int(36 * u)

        y += int(10 * u)
        pygame.draw.line(surf, (60, 62, 76), (x, y), (right, y))
        y += int(16 * u)
        ur, mean = self.unstable_rate()
        cells = [("COMBO", str(self.combo)), ("MAX COMBO", str(self.max_combo)),
                 ("UR", f"{ur:.1f}"), ("MEAN", f"{mean:+.1f} ms")]
        col_w = (right - x) // 2
        for k, (label, value) in enumerate(cells):
            cx = x + (k % 2) * col_w
            cy = y + (k // 2) * int(62 * u)
            surf.blit(self.text(self.f_label, label, MUTED), (cx, cy))
            surf.blit(self.text(self.f_med, value, TEXT), (cx, cy + int(20 * u)))

    def _draw_error_bar(self, surf, now):
        u, rate = self.u, self.rep.rate
        w50 = self.win.w50
        tick_w = max(2, int(3 * u))
        for t, off, j in self.recent_offsets:
            age = (now - t) / rate
            if age < 0:
                continue
            a = int(230 * (1 - age / 4000))
            if a <= 0:
                continue
            xx = self.eb_cx + int(max(-w50, min(w50, off)) * self.eb_scale)
            tick = pygame.Surface((tick_w, self.eb_h + int(14 * u)), pygame.SRCALPHA, 32)
            tick.fill((*((255, 255, 255) if j == judge.MAX else JUDGE_COLORS[j]), a))
            surf.blit(tick, (xx - tick_w // 2, self.eb_y - int(7 * u)))
        _, mean = self.unstable_rate()
        if self.off_n >= 2:
            mx = self.eb_cx + int(max(-w50, min(w50, mean * rate)) * self.eb_scale)
            ty = self.eb_y - int(12 * u)
            s = int(7 * u)
            pygame.draw.polygon(surf, GOLD, [(mx - s, ty - s), (mx + s, ty - s), (mx, ty)])

    def _draw_progress(self, surf, now):
        span = max(1, self.map_end - self.map_start)
        p = max(0.0, min(1.0, (now - self.map_start) / span))
        h = max(3, int(4 * self.u))
        pygame.draw.rect(surf, (30, 30, 42), (0, 0, self.W, h))
        pygame.draw.rect(surf, skins.BLUE, (0, 0, int(self.W * p), h))

    def draw_results(self, surf, now, fade):
        """Results card shown after the map ends. fade goes 0..1."""
        self.draw(surf, now)
        u = self.u
        shade = pygame.Surface((self.W, self.H), pygame.SRCALPHA, 32)
        shade.fill((6, 6, 12, int(225 * fade)))
        surf.blit(shade, (0, 0))
        if fade <= 0.05:
            return
        rep, bm = self.rep, self.bm
        layer = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        cw, ch = int(720 * u), int(560 * u)
        rect = pygame.Rect((self.W - cw) // 2, (self.H - ch) // 2, cw, ch)
        self.card(layer, rect)
        cx = rect.centerx
        y = rect.y + int(34 * u)

        def center(t, gap):
            nonlocal y
            layer.blit(t, (cx - t.get_width() // 2, y))
            y += int(gap * u)

        maxw = cw - 2 * self.pad
        center(self.text(self.f_title, self.fit(self.f_title, f"{bm.artist} - {bm.title}", maxw), TEXT), 40)
        center(self.text(self.f_small_b, self.fit(self.f_small_b, f"[{bm.version}]", maxw), GOLD), 34)
        self._player_tag(layer, cx, y, center=True)
        y += int(34 * u)
        if rep.mod_string:
            center(self.text(self.f_small_b, "+" + rep.mod_string, GOLD), 16)
        y += int(16 * u)
        center(self.text(self.f_combo, f"{rep.score:,}".replace(",", "."), TEXT), 92)
        stats = [rep.count_geki, rep.count_300, rep.count_katu, rep.count_100, rep.count_50, rep.count_miss]
        total = sum(stats) or 1
        acc = 100 * sum(c * w for c, w in zip(stats, judge.ACC_WEIGHT)) / (300 * total)
        center(self.text(self.f_big, f"{acc:.2f}%", GOLD), 74)

        colx = [rect.x + int(120 * u), rect.x + cw // 2 + int(60 * u)]
        for j in range(6):
            col, row = j % 2, j // 2
            yy = y + row * int(42 * u)
            layer.blit(self.text(self.f_med, judge.NAMES[j], JUDGE_COLORS[j]), (colx[col], yy))
            v = self.text(self.f_med, str(stats[j]), TEXT)
            layer.blit(v, (colx[col] + int(190 * u) - v.get_width(), yy))
        y += 3 * int(42 * u) + int(26 * u)
        ur, _ = self.unstable_rate()
        fc = "  Full Combo" if rep.perfect else ""
        center(self.text(self.f_med, f"Max combo {rep.max_combo}   UR {ur:.1f}{fc}", (220, 222, 232)), 40)
        layer.set_alpha(int(255 * fade))
        surf.blit(layer, (0, 0))
