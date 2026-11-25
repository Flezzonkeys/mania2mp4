"""Frame renderer and ffmpeg pipeline for osu!mania replays."""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from . import judge  # noqa: E402

WHITE = (235, 238, 248)
BLUE = (92, 190, 255)
GOLD = (255, 204, 90)

JUDGE_COLORS = [
    (180, 240, 255),  # MAX
    (255, 214, 92),   # 300
    (120, 230, 120),  # 200
    (90, 160, 255),   # 100
    (170, 170, 180),  # 50
    (255, 80, 80),    # MISS
]


def column_colors(keys: int):
    presets = {
        1: [GOLD],
        2: [WHITE, WHITE],
        3: [WHITE, GOLD, WHITE],
        4: [WHITE, BLUE, BLUE, WHITE],
        5: [WHITE, BLUE, GOLD, BLUE, WHITE],
        6: [WHITE, BLUE, WHITE, WHITE, BLUE, WHITE],
        7: [WHITE, BLUE, WHITE, GOLD, WHITE, BLUE, WHITE],
        8: [GOLD, WHITE, BLUE, WHITE, WHITE, BLUE, WHITE, GOLD],
    }
    if keys in presets:
        return presets[keys]
    cols = [WHITE if i % 2 == 0 else BLUE for i in range(keys)]
    if keys % 2:
        cols[keys // 2] = GOLD
    return cols


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


def _scale(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


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


class Scene:
    def __init__(self, bm, replay, results, win, opts: RenderOptions):
        pygame.font.init()
        self.bm, self.rep, self.res, self.win, self.o = bm, replay, results, win, opts
        W, H = opts.width, opts.height
        self.W, self.H = W, H
        self.u = H / 1080.0  # layout unit
        u = self.u

        self.keys = bm.keys
        self.col_w = int(min(110, 560 / self.keys) * u)
        self.field_w = self.col_w * self.keys
        self.field_x = (W - self.field_w) // 2
        self.hit_y = int(900 * u)
        self.note_h = int(34 * u)
        self.px_per_ms = self.hit_y / (opts.scroll_ms * replay.rate)  # map ms -> px
        self.colors = column_colors(self.keys)

        fb, fr = _font_path(True), _font_path(False)
        self.f_combo = pygame.font.Font(fb, int(72 * u))
        self.f_judge = pygame.font.Font(fb, int(56 * u))
        self.f_big = pygame.font.Font(fb, int(44 * u))
        self.f_med = pygame.font.Font(fb, int(28 * u))
        self.f_small = pygame.font.Font(fr, int(22 * u))
        self.f_tiny = pygame.font.Font(fr, int(18 * u))
        self._text_cache = {}

        self._build_static()
        self._build_sprites()
        self._prepare_timeline()

    # ---------- setup ----------

    def text(self, font, s, color):
        key = (id(font), s, color)
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 4000:
                self._text_cache.clear()
            surf = font.render(s, True, color)
            self._text_cache[key] = surf
        return surf

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
                img = img.filter(ImageFilter.GaussianBlur(radius=8 * self.u))
                surf = pygame.image.frombytes(img.tobytes(), (W, H), "RGB")
                dim = pygame.Surface((W, H))
                dim.fill((0, 0, 0))
                dim.set_alpha(int(255 * self.o.bg_dim))
                surf.blit(dim, (0, 0))
                return surf
            except Exception as exc:  # noqa: BLE001
                print(f"Background could not be loaded: {exc}", file=sys.stderr)
        surf = pygame.Surface((W, H))
        surf.fill((14, 14, 22))
        return surf

    def _build_static(self):
        u = self.u
        bg = self._load_background()
        field = pygame.Surface((self.field_w, self.H), pygame.SRCALPHA)
        field.fill((0, 0, 0, 215))
        for c in range(1, self.keys):
            pygame.draw.line(field, (255, 255, 255, 22), (c * self.col_w, 0), (c * self.col_w, self.H))
        bg.blit(field, (self.field_x, 0))
        # Edges of the playfield
        edge = (255, 255, 255)
        pygame.draw.line(bg, _scale(edge, 0.35), (self.field_x - 1, 0), (self.field_x - 1, self.H), max(1, int(2 * u)))
        pygame.draw.line(bg, _scale(edge, 0.35), (self.field_x + self.field_w, 0),
                         (self.field_x + self.field_w, self.H), max(1, int(2 * u)))
        # Judgement line
        pygame.draw.rect(bg, (230, 230, 240), (self.field_x, self.hit_y, self.field_w, max(2, int(3 * u))))

        # Static texts: map info, player and mods
        bm, rep = self.bm, self.rep
        x, y = int(36 * u), int(30 * u)
        bg.blit(self.text(self.f_med, f"{bm.artist} - {bm.title}", (255, 255, 255)), (x, y))
        y += int(38 * u)
        bg.blit(self.text(self.f_small, f"[{bm.version}]  mapped by {bm.creator}", (200, 205, 220)), (x, y))
        y += int(30 * u)
        info = f"{bm.keys}K  OD {bm.od:g}  HP {bm.hp:g}"
        bg.blit(self.text(self.f_small, info, (200, 205, 220)), (x, y))
        y += int(44 * u)
        bg.blit(self.text(self.f_med, f"Played by {rep.player}", (255, 255, 255)), (x, y))
        if rep.mod_string:
            y += int(38 * u)
            bg.blit(self.text(self.f_med, "+" + rep.mod_string, GOLD), (x, y))

        # Hit error bar zones
        self.eb_w = int(360 * u)
        self.eb_h = int(10 * u)
        self.eb_x = (self.W - self.eb_w) // 2
        self.eb_y = int(1050 * u)
        self.eb_scale = (self.eb_w / 2) / self.win.w50
        cx = self.W // 2
        zones = [(self.win.w50, JUDGE_COLORS[4]), (self.win.w100, JUDGE_COLORS[3]),
                 (self.win.w200, JUDGE_COLORS[2]), (self.win.w300, JUDGE_COLORS[1]),
                 (self.win.max, JUDGE_COLORS[0])]
        for w, col in zones:
            half = int(w * self.eb_scale)
            pygame.draw.rect(bg, _scale(col, 0.45), (cx - half, self.eb_y, half * 2, self.eb_h))
        pygame.draw.rect(bg, (255, 255, 255), (cx - 1, self.eb_y - int(8 * u), 2, self.eb_h + int(16 * u)))

        self.static = pygame.Surface((self.W, self.H), 0, 32)
        self.static.blit(bg, (0, 0))

    def _rounded(self, w, h, color, radius, alpha=255):
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(s, (*color, alpha), (0, 0, w, h), border_radius=radius)
        return s

    def _build_sprites(self):
        u = self.u
        pad = max(1, int(3 * u))
        w = self.col_w - pad * 2
        rad = int(6 * u)
        self.pad = pad
        self.note_sprites = []
        self.note_dim = []
        for col in self.colors:
            s = self._rounded(w, self.note_h, col, rad)
            hl = self._rounded(w - 2 * pad, max(2, self.note_h // 3), _scale(col, 1.15), rad // 2)
            hl.set_alpha(120)
            s.blit(hl, (pad, pad))
            self.note_sprites.append(s)
            d = self._rounded(w, self.note_h, _scale(col, 0.35), rad)
            self.note_dim.append(d)

        # Key light beams (gradient above the judgement line)
        beam_h = int(380 * u)
        self.beams = []
        for col in self.colors:
            s = pygame.Surface((self.col_w, beam_h), pygame.SRCALPHA)
            for y in range(beam_h):
                a = int(110 * (y / beam_h) ** 2.2)
                pygame.draw.line(s, (*col, a), (0, y), (self.col_w, y))
            self.beams.append(s)
        self.beam_h = beam_h

        # Receptors
        rh = int(1080 * u) - self.hit_y - int(60 * u)
        self.receptor_h = rh
        self.rec_up, self.rec_down = [], []
        for col in self.colors:
            self.rec_up.append(self._rounded(self.col_w - pad * 2, rh, _scale(col, 0.22), rad))
            down = self._rounded(self.col_w - pad * 2, rh, _scale(col, 0.85), rad)
            self.rec_down.append(down)

        # Hit flash
        fh = int(90 * u)
        self.flash = []
        for col in self.colors:
            s = pygame.Surface((self.col_w, fh), pygame.SRCALPHA)
            for y in range(fh):
                d = abs(y - fh / 2) / (fh / 2)
                a = int(200 * (1 - d) ** 2)
                pygame.draw.line(s, (*_scale(col, 1.2), a), (0, y), (self.col_w, y))
            self.flash.append(s)
        self.flash_h = fh

    def _prepare_timeline(self):
        notes, res = self.bm.notes, self.res
        self.events = sorted(range(len(notes)), key=lambda i: res[i].judged_at)
        self.ev_pos = 0
        self.counts = [0] * 6
        self.combo = 0
        self.max_combo = 0
        self.last_judgement = None  # (judgement, time)
        self.recent_offsets = []    # (time, offset, judgement)
        self.last_hit = [-10 ** 9] * self.keys
        self.key_state = self.rep.frames
        self.frame_pos = 0
        self.cur_keys = 0
        # Visible-window bookkeeping: notes sorted by time, sliding start index
        self.first_visible = 0
        ends = [(n.end if n.is_hold else n.time) for n in notes]
        self.max_len = max([e - n.time for e, n in zip(ends, notes)] + [0])
        first = notes[0].time if notes else 0
        last = max(ends) if ends else 0
        self.map_start = first
        self.map_end = last

    # ---------- per frame ----------

    def _advance(self, now):
        res = self.res
        while self.ev_pos < len(self.events) and res[self.events[self.ev_pos]].judged_at <= now:
            i = self.events[self.ev_pos]
            r = res[i]
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
            self.ev_pos += 1
        # Column flashes on key-down of hits
        frames = self.key_state
        while self.frame_pos < len(frames) and frames[self.frame_pos][0] <= now:
            t, k = frames[self.frame_pos]
            newly = k & ~self.cur_keys
            for c in range(self.keys):
                if newly & (1 << c):
                    self.last_hit[c] = t
            self.cur_keys = k
            self.frame_pos += 1
        cutoff = now - 4000 * self.rep.rate
        if self.recent_offsets and self.recent_offsets[0][0] < cutoff:
            self.recent_offsets = [x for x in self.recent_offsets if x[0] >= cutoff]

    def accuracy(self):
        total = sum(self.counts)
        if not total:
            return 100.0
        pts = sum(c * w for c, w in zip(self.counts, judge.ACC_WEIGHT))
        return 100.0 * pts / (300 * total)

    def draw(self, surf, now):
        self._advance(now)
        u = self.u
        surf.blit(self.static, (0, 0))
        rate = self.rep.rate
        fx, cw, hy = self.field_x, self.col_w, self.hit_y

        # Beams for held keys
        for c in range(self.keys):
            if self.cur_keys & (1 << c):
                surf.blit(self.beams[c], (fx + c * cw, hy - self.beam_h))

        # Notes
        notes, res = self.bm.notes, self.res
        ppm = self.px_per_ms
        top_time = now + hy / ppm + 50
        # Skip notes whose end has long passed
        while self.first_visible < len(notes) and notes[self.first_visible].time + self.max_len < now - 2000:
            self.first_visible += 1
        nh = self.note_h
        for i in range(self.first_visible, len(notes)):
            n = notes[i]
            if n.time > top_time:
                break
            r = res[i]
            x = fx + n.column * cw + self.pad
            if not n.is_hold:
                if r.judgement != judge.MISS and r.hit_time is not None and now >= r.hit_time:
                    continue
                y = hy - (n.time - now) * ppm
                if y - nh > self.H:
                    continue
                sprite = self.note_dim[n.column] if (r.judgement == judge.MISS and now > n.time) else self.note_sprites[n.column]
                surf.blit(sprite, (x, int(y - nh)))
                continue

            # Hold note
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
            y_head = hy - (head_t - now) * ppm
            y_tail = hy - (n.end - now) * ppm
            if y_tail - nh > self.H:
                continue
            missed = r.judgement == judge.MISS and now > n.time + self.win.w50
            dead = missed or (released and r.release_time < n.end)
            col = self.colors[n.column]
            body_col = _scale(col, 0.25 if dead else (0.85 if held else 0.55))
            bw = cw - self.pad * 2
            inset = int(bw * 0.12)
            top = int(y_tail - nh / 2)
            bottom = int(y_head - nh / 2)
            if bottom > top:
                pygame.draw.rect(surf, body_col, (x + inset, top, bw - 2 * inset, bottom - top))
            # Tail cap
            pygame.draw.rect(surf, body_col, (x + inset, top - int(6 * u), bw - 2 * inset, int(10 * u)),
                             border_radius=int(4 * u))
            sprite = self.note_dim[n.column] if dead else self.note_sprites[n.column]
            surf.blit(sprite, (x, int(y_head - nh)))

        # Receptors and flashes
        ry = hy + int(6 * u)
        for c in range(self.keys):
            pressed = self.cur_keys & (1 << c)
            spr = self.rec_down[c] if pressed else self.rec_up[c]
            surf.blit(spr, (fx + c * cw + self.pad, ry))
            age = (now - self.last_hit[c]) / rate
            if 0 <= age < 140:
                fl = self.flash[c]
                fl.set_alpha(int(255 * (1 - age / 140)))
                surf.blit(fl, (fx + c * cw, hy - self.flash_h // 2))

        cx = self.W // 2
        # Judgement popup
        if self.last_judgement:
            j, t = self.last_judgement
            age = (now - t) / rate
            if age < 450:
                txt = self.text(self.f_judge, judge.NAMES[j], JUDGE_COLORS[j])
                grow = 1.0 + 0.25 * max(0.0, 1 - age / 80)
                if grow > 1.001:
                    txt = pygame.transform.smoothscale(
                        txt, (int(txt.get_width() * grow), int(txt.get_height() * grow)))
                alpha = 255 if age < 300 else int(255 * (1 - (age - 300) / 150))
                txt.set_alpha(alpha)
                surf.blit(txt, (cx - txt.get_width() // 2, int(560 * u) - txt.get_height() // 2))
                txt.set_alpha(255)

        # Combo
        if self.combo >= 2:
            c = self.text(self.f_combo, str(self.combo), (255, 255, 255))
            surf.blit(c, (cx - c.get_width() // 2, int(380 * u)))

        # Hit error bar ticks
        ebx, eby = cx, self.eb_y
        for t, off, j in self.recent_offsets:
            age = (now - t) / rate
            if age < 0:
                continue
            a = max(0, int(230 * (1 - age / 4000)))
            if a <= 0:
                continue
            xx = ebx + int(max(-self.win.w50, min(self.win.w50, off)) * self.eb_scale)
            tick = pygame.Surface((max(2, int(3 * u)), self.eb_h + int(14 * u)))
            tick.fill((255, 255, 255) if j == judge.MAX else JUDGE_COLORS[j])
            tick.set_alpha(a)
            surf.blit(tick, (xx - 1, eby - int(7 * u)))

        self._draw_side_panel(surf)
        self._draw_progress(surf, now)

    def _draw_side_panel(self, surf):
        u = self.u
        x = self.field_x + self.field_w + int(60 * u)
        y = int(300 * u)
        acc = self.text(self.f_big, f"{self.accuracy():.2f}%", (255, 255, 255))
        surf.blit(acc, (x, y))
        y += int(70 * u)
        for j in range(6):
            name = self.text(self.f_small, judge.NAMES[j], JUDGE_COLORS[j])
            val = self.text(self.f_small, str(self.counts[j]), (240, 240, 245))
            surf.blit(name, (x, y))
            surf.blit(val, (x + int(110 * u), y))
            y += int(34 * u)
        y += int(14 * u)
        mc = self.text(self.f_small, f"Max combo  {self.max_combo}", (200, 205, 220))
        surf.blit(mc, (x, y))

    def _draw_progress(self, surf, now):
        span = max(1, self.map_end - self.map_start)
        p = max(0.0, min(1.0, (now - self.map_start) / span))
        h = max(3, int(5 * self.u))
        pygame.draw.rect(surf, (40, 40, 55), (0, 0, self.W, h))
        pygame.draw.rect(surf, BLUE, (0, 0, int(self.W * p), h))

    def draw_results(self, surf, now, fade):
        """Results overlay shown after the map ends. fade goes 0..1."""
        self.draw(surf, now)
        u = self.u
        shade = pygame.Surface((self.W, self.H))
        shade.fill((6, 6, 12))
        shade.set_alpha(int(245 * fade))
        surf.blit(shade, (0, 0))
        if fade <= 0.05:
            return
        a = int(255 * fade)
        rep, bm = self.rep, self.bm
        cx = self.W // 2
        y = int(180 * u)

        def line(font, s, color, gap):
            nonlocal y
            t = self.text(font, s, color)
            t.set_alpha(a)
            surf.blit(t, (cx - t.get_width() // 2, y))
            t.set_alpha(255)
            y += int(gap * u)

        line(self.f_med, f"{bm.artist} - {bm.title} [{bm.version}]", (255, 255, 255), 50)
        mods = f"  +{rep.mod_string}" if rep.mod_string else ""
        line(self.f_small, f"Played by {rep.player}{mods}", (200, 205, 220), 70)
        line(self.f_combo, f"{rep.score:,}".replace(",", "."), (255, 255, 255), 100)
        stats = [rep.count_geki, rep.count_300, rep.count_katu, rep.count_100, rep.count_50, rep.count_miss]
        total = sum(stats) or 1
        acc = 100 * sum(c * w for c, w in zip(stats, judge.ACC_WEIGHT)) / (300 * total)
        line(self.f_big, f"{acc:.2f}%", GOLD, 80)
        for j in range(6):
            line(self.f_med, f"{judge.NAMES[j]}   {stats[j]}", JUDGE_COLORS[j], 42)
        y += int(20 * u)
        fc = "  (Full Combo)" if rep.perfect else ""
        line(self.f_med, f"Max combo {rep.max_combo}{fc}", (230, 230, 240), 40)


# ---------- ffmpeg ----------

def _vaapi_device() -> str | None:
    for i in range(128, 136):
        dev = f"/dev/dri/renderD{i}"
        if os.path.exists(dev) and os.access(dev, os.R_OK | os.W_OK):
            return dev
    return None


def _probe_sample_rate(path: Path) -> int:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=sample_rate", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 44100


def _ffmpeg_cmd(opts, out_path, audio_path, audio_start_ms, video_seconds, rate, nightcore, encoder):
    W, H = opts.width, opts.height
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if encoder == "vaapi":
        cmd += ["-vaapi_device", _vaapi_device()]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr0", "-s", f"{W}x{H}", "-r", str(opts.fps), "-i", "-"]

    has_audio = audio_path is not None and audio_path.is_file()
    if has_audio:
        start = audio_start_ms / 1000.0
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(audio_path)]
        filters = []
        if start < 0:
            ms = int(-start * 1000)
            filters.append(f"adelay={ms}:all=1")
        if rate != 1.0:
            if nightcore:
                sr = _probe_sample_rate(audio_path)
                filters.append(f"asetrate={int(sr * rate)},aresample={sr}")
            else:
                filters.append(f"atempo={rate}")
        fade_start = max(0.0, video_seconds - opts.results_s)
        filters.append(f"afade=t=out:st={fade_start:.3f}:d={min(3.0, opts.results_s):.3f}")
        filters.append("apad")
        cmd += ["-filter:a", ",".join(filters), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k",
                "-shortest"]

    if encoder == "vaapi":
        cmd += ["-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-rc_mode", "CQP", "-qp", str(opts.quality)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(max(0, opts.quality - 2)),
                "-pix_fmt", "yuv420p"]
    cmd += ["-movflags", "+faststart", str(out_path)]
    return cmd


def pick_encoder(choice: str) -> str:
    if choice in ("vaapi", "x264"):
        return choice
    if _vaapi_device():
        test = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-vaapi_device", _vaapi_device(),
             "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1", "-vf", "format=nv12,hwupload",
             "-c:v", "h264_vaapi", "-f", "null", "-"], capture_output=True, timeout=30)
        if test.returncode == 0:
            return "vaapi"
    return "x264"


def render_video(bm, replay, results, win, out_path: Path, opts: RenderOptions, progress=None):
    from .osr import MOD_NC

    scene = Scene(bm, replay, results, win, opts)
    rate = replay.rate
    lead = 2000 * rate
    start = opts.start_ms if opts.start_ms is not None else scene.map_start - lead
    end = scene.map_end + 1500 * rate
    play_seconds = (end - start) / 1000.0 / rate
    if opts.duration_s is not None:
        play_seconds = min(play_seconds, opts.duration_s)
        results_s = 0.0
    else:
        results_s = opts.results_s
    total_seconds = play_seconds + results_s
    n_frames = int(total_seconds * opts.fps)
    n_play = int(play_seconds * opts.fps)

    encoder = pick_encoder(opts.encoder)
    opts_r = RenderOptions(**{**opts.__dict__, "results_s": results_s})
    # Audio: map time `start` corresponds to video time 0.
    audio_start = (start + opts.offset_ms)
    cmd = _ffmpeg_cmd(opts_r, out_path, bm.audio_path, audio_start, total_seconds, rate,
                      bool(replay.mods & MOD_NC), encoder)

    surf = pygame.Surface((opts.width, opts.height), 0, 32)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    last_report = 0.0
    try:
        for f in range(n_frames):
            vt = f / opts.fps
            if f < n_play:
                now = start + vt * 1000 * rate
                scene.draw(surf, now)
            else:
                now = start + play_seconds * 1000 * rate
                fade = min(1.0, (vt - play_seconds) / 0.6)
                scene.draw_results(surf, now, fade)
            proc.stdin.write(surf.get_buffer().raw)
            el = time.time() - t0
            if progress and (el - last_report > 0.5 or f == n_frames - 1):
                last_report = el
                progress(f + 1, n_frames, el, encoder)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {code}")
    return encoder
