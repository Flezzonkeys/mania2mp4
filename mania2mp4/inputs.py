"""Keyboard input overlay: key boxes with labels, key rain, press counters and KPS."""

import bisect
import re
from pathlib import Path

import pygame

from .judge import key_events

# osu! stable (.NET Keys enum) names -> short labels
KEY_NAMES = {
    "OemPeriod": ".", "OemComma": ",", "OemQuestion": "/", "OemSemicolon": ";",
    "OemQuotes": "'", "OemMinus": "-", "OemPlus": "=", "OemOpenBrackets": "[",
    "OemCloseBrackets": "]", "OemPipe": "\\", "OemBackslash": "\\", "OemTilde": "`",
    "Space": "SPC", "LeftShift": "LSH", "RightShift": "RSH", "ShiftKey": "SHF",
    "LeftControl": "LCT", "RightControl": "RCT", "ControlKey": "CTL", "LeftAlt": "LAL",
    "RightAlt": "RAL", "Menu": "ALT", "Capital": "CAP", "CapsLock": "CAP", "Tab": "TAB",
    "Return": "ENT", "Enter": "ENT", "Back": "BSP", "Left": "<", "Right": ">", "Up": "^", "Down": "v",
}


def _label(name: str) -> str:
    if name in KEY_NAMES:
        return KEY_NAMES[name]
    m = re.fullmatch(r"D(\d)", name)
    if m:
        return m.group(1)
    m = re.fullmatch(r"NumPad(\d)", name)
    if m:
        return "N" + m.group(1)
    return name[:3].upper() if len(name) > 1 else name.upper()


def load_key_labels(songs_dir: Path | None, keys: int) -> list[str] | None:
    """Read the mania key layout from osu! stable's osu!.<user>.cfg."""
    if not songs_dir:
        return None
    for cfg in sorted(Path(songs_dir).parent.glob("osu!.*.cfg")):
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        layout = re.search(rf"^ManiaLayouts{keys}K\s*=\s*(.+)$", text, re.M)
        if not layout:
            continue
        sel = re.search(rf"^ManiaLayoutSelected{keys}K\s*=\s*(\d+)", text, re.M)
        options = layout.group(1).strip().split("|")
        idx = int(sel.group(1)) if sel else 0
        names = options[min(idx, len(options) - 1)].split()
        if len(names) == keys:
            return [_label(n) for n in names]
    return None


class InputOverlay:
    def __init__(self, scene, labels):
        self.s = scene
        u = scene.u
        self.keys = scene.keys
        self.labels = labels or [str(i + 1) for i in range(self.keys)]
        self.box = int(min(64, 380 / self.keys) * u)
        self.gap = int(8 * u)
        self.width = self.keys * self.box + (self.keys - 1) * self.gap
        self.x = scene.field_x - int(70 * u) - self.width
        self.box_y = int(975 * u)
        self.rain_top = int(470 * u)
        self.rain_bottom = self.box_y - int(10 * u)
        self.speed = 0.55 * u  # px per real ms
        self.rate = scene.rep.rate
        self.visible_ms = (self.rain_bottom - self.rain_top) / self.speed * self.rate  # map ms

        self.colors = scene.colors_by_column
        self.intervals = key_events(scene.rep.frames, self.keys)
        self.press_times = [[p for p, _ in col] for col in self.intervals]
        self.all_presses = sorted(p for col in self.press_times for p in col)
        self.first = [0] * self.keys

        f_label = pygame.font.Font(scene.font_bold, int(self.box * 0.42))
        f_count = pygame.font.Font(scene.font_regular, int(self.box * 0.24))
        self.f_count = f_count
        self.box_up, self.box_down, self.label_up, self.label_down = [], [], [], []
        rad = int(8 * u)
        for c in range(self.keys):
            col = self.colors[c]
            up = pygame.Surface((self.box, self.box), pygame.SRCALPHA)
            pygame.draw.rect(up, (20, 20, 28, 210), (0, 0, self.box, self.box), border_radius=rad)
            pygame.draw.rect(up, (*col, 200), (0, 0, self.box, self.box), max(1, int(2 * u)), border_radius=rad)
            down = pygame.Surface((self.box, self.box), pygame.SRCALPHA)
            pygame.draw.rect(down, (*col, 255), (0, 0, self.box, self.box), border_radius=rad)
            self.box_up.append(up)
            self.box_down.append(down)
            self.label_up.append(f_label.render(self.labels[c], True, (240, 240, 248)))
            self.label_down.append(f_label.render(self.labels[c], True, (16, 16, 22)))

        # Fade mask for the top of the key rain
        self.fade_h = int(80 * u)

    def draw(self, surf, now):
        s, u = self.s, self.s.u
        cur = s.cur_keys
        spd = self.speed / self.rate  # px per map ms
        clip = pygame.Rect(self.x, self.rain_top, self.width, self.rain_bottom - self.rain_top)
        surf.set_clip(clip)
        for c in range(self.keys):
            iv = self.intervals[c]
            i = self.first[c]
            while i < len(iv) and iv[i][1] < now - self.visible_ms:
                i += 1
            self.first[c] = i
            x = self.x + c * (self.box + self.gap)
            col = self.colors[c]
            for press, release in iv[i:]:
                if press > now:
                    break
                y_bottom = self.rain_bottom - max(0.0, now - release) * spd
                y_top = self.rain_bottom - (now - press) * spd
                h = max(int(4 * u), int(y_bottom - y_top))
                pygame.draw.rect(surf, col, (x + int(self.box * 0.15), int(y_bottom - h), int(self.box * 0.7), h),
                                 border_radius=int(3 * u))
        surf.set_clip(None)

        # Soft fade at the top of the rain
        fade_rect = pygame.Rect(self.x, self.rain_top, self.width, self.fade_h)
        region = surf.subsurface(fade_rect)
        for y in range(0, self.fade_h, 4):
            a = int(255 * (1 - y / self.fade_h) ** 1.5)
            if a <= 0:
                continue
            strip = s.static.subsurface((self.x, self.rain_top + y, self.width, min(4, self.fade_h - y)))
            strip.set_alpha(a)
            region.blit(strip, (0, y))
            strip.set_alpha(None)

        # Key boxes, labels, counters
        for c in range(self.keys):
            x = self.x + c * (self.box + self.gap)
            pressed = cur & (1 << c)
            surf.blit(self.box_down[c] if pressed else self.box_up[c], (x, self.box_y))
            lab = self.label_down[c] if pressed else self.label_up[c]
            surf.blit(lab, (x + (self.box - lab.get_width()) // 2, self.box_y + int(self.box * 0.08)))
            n = bisect.bisect_right(self.press_times[c], now)
            cnt = s.text(self.f_count, str(n), (16, 16, 22) if pressed else (200, 202, 215))
            surf.blit(cnt, (x + (self.box - cnt.get_width()) // 2, self.box_y + int(self.box * 0.62)))

        # KPS and total
        total = bisect.bisect_right(self.all_presses, now)
        kps = total - bisect.bisect_right(self.all_presses, now - 1000 * self.rate)
        t = s.text(s.f_med, f"{kps} KPS", (255, 255, 255))
        surf.blit(t, (self.x, self.rain_top - int(44 * u)))
        t2 = s.text(s.f_small, f"{total} presses", (200, 205, 220))
        surf.blit(t2, (self.x + self.width - t2.get_width(), self.rain_top - int(40 * u)))
