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
    """Draws inside `rect` (a card already painted on the static background)."""

    def __init__(self, scene, labels, rect):
        self.s = scene
        u = scene.u
        self.keys = scene.keys
        self.labels = labels or [str(i + 1) for i in range(self.keys)]
        pad = int(22 * u)
        self.rect = rect
        inner_w = rect.width - 2 * pad
        self.gap = int(10 * u)
        self.box = int(min(72 * u, (inner_w - (self.keys - 1) * self.gap) / self.keys))
        self.width = self.keys * self.box + (self.keys - 1) * self.gap
        self.x = rect.x + (rect.width - self.width) // 2
        self.pad = pad
        self.header_y = rect.y + int(18 * u)
        self.box_y = rect.bottom - pad - self.box
        self.rain_top = rect.y + int(78 * u)
        self.rain_bottom = self.box_y - int(10 * u)
        self.speed = 0.55 * u  # px per real ms
        self.rate = scene.rep.rate
        self.visible_ms = (self.rain_bottom - self.rain_top) / self.speed * self.rate  # map ms

        self.colors = scene.colors_by_column
        self.intervals = key_events(scene.rep.frames, self.keys)
        self.press_times = [[p for p, _ in col] for col in self.intervals]
        self.all_presses = sorted(p for col in self.press_times for p in col)
        self.first = [0] * self.keys

        f_label = pygame.font.Font(scene.font_bold, int(self.box * 0.40))
        self.f_count = pygame.font.Font(scene.font_regular, int(self.box * 0.24))
        self.box_up, self.box_down, self.label_up, self.label_down = [], [], [], []
        rad = int(10 * u)
        for c in range(self.keys):
            col = self.colors[c]
            up = pygame.Surface((self.box, self.box), pygame.SRCALPHA)
            pygame.draw.rect(up, (28, 29, 38, 255), (0, 0, self.box, self.box), border_radius=rad)
            pygame.draw.rect(up, (*col, 150), (0, 0, self.box, self.box), max(1, int(2 * u)), border_radius=rad)
            down = pygame.Surface((self.box, self.box), pygame.SRCALPHA)
            pygame.draw.rect(down, (*col, 255), (0, 0, self.box, self.box), border_radius=rad)
            self.box_up.append(up)
            self.box_down.append(down)
            self.label_up.append(f_label.render(self.labels[c], True, (240, 240, 248)))
            self.label_down.append(f_label.render(self.labels[c], True, (16, 16, 22)))
        self.fade_h = int(60 * u)
        self._fade = None

    def _fade_overlay(self):
        if self._fade is None:
            src = self.s.static.subsurface((self.x, self.rain_top, self.width, self.fade_h))
            fade = pygame.Surface(src.get_size(), pygame.SRCALPHA, 32)
            fade.blit(src, (0, 0))
            alpha = pygame.surfarray.pixels_alpha(fade)
            for y in range(self.fade_h):
                alpha[:, y] = int(255 * (1 - y / self.fade_h) ** 1.5)
            del alpha
            self._fade = fade
        return self._fade

    def draw(self, surf, now):
        s, u = self.s, self.s.u
        cur = s.cur_keys
        spd = self.speed / self.rate  # px per map ms
        surf.set_clip(pygame.Rect(self.x, self.rain_top, self.width, self.rain_bottom - self.rain_top))
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
                pygame.draw.rect(surf, col, (x + int(self.box * 0.2), int(y_bottom - h), int(self.box * 0.6), h),
                                 border_radius=int(3 * u))
        surf.set_clip(None)

        # Fade the rain out at the top with a pre-built overlay of the background
        surf.blit(self._fade_overlay(), (self.x, self.rain_top))

        # Header: KPS and total presses
        total = bisect.bisect_right(self.all_presses, now)
        kps = total - bisect.bisect_right(self.all_presses, now - 1000 * self.rate)
        hx = self.rect.x + self.pad
        surf.blit(s.text(s.f_label, "INPUTS", (150, 154, 172)), (hx, self.header_y))
        k = s.text(s.f_med, f"{kps} KPS", (255, 255, 255))
        surf.blit(k, (hx, self.header_y + int(18 * u)))
        t = s.text(s.f_small, f"{total} presses", (150, 154, 172))
        surf.blit(t, (self.rect.right - self.pad - t.get_width(), self.header_y + int(22 * u)))

        # Key boxes with labels and counters
        for c in range(self.keys):
            x = self.x + c * (self.box + self.gap)
            pressed = cur & (1 << c)
            surf.blit(self.box_down[c] if pressed else self.box_up[c], (x, self.box_y))
            lab = self.label_down[c] if pressed else self.label_up[c]
            surf.blit(lab, (x + (self.box - lab.get_width()) // 2, self.box_y + int(self.box * 0.10)))
            n = bisect.bisect_right(self.press_times[c], now)
            cnt = s.text(self.f_count, str(n), (16, 16, 22) if pressed else (180, 182, 196))
            surf.blit(cnt, (x + (self.box - cnt.get_width()) // 2, self.box_y + int(self.box * 0.62)))
