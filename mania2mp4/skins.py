"""Built-in note skins (arrow, bar) and rhythm (snap) colouring.

Every skin exposes the same interface, used by render.Scene:
  col_x, col_w, field_x, field_w   column geometry in pixels
  rc_y                             y of the receptor centre (where a note's centre is when it must be hit)
  keys_under_notes                 draw receptors before notes
  judge_y, combo_y                 centre y of the judgement popup and the combo counter
  note(c, color, dim)              note sprite
  body(surf, c, color, top, bottom, state)   hold body between two centre positions
  tail(surf, c, color, y, state)   hold end
  receptors(surf, pressed_mask)
  effects(surf, now, last_hit, rate)
  judgement(j) / combo(n)          sprites, or None to let the scene draw text
  stage(bg)                        static decoration drawn once
"""

import bisect

import pygame

WHITE = (235, 238, 248)
BLUE = (92, 190, 255)
GOLD = (255, 204, 90)

LEFT, DOWN, UP, RIGHT, CENTER = "L", "D", "U", "R", "C"

ARROW_LAYOUTS = {
    1: [CENTER],
    2: [LEFT, RIGHT],
    3: [LEFT, CENTER, RIGHT],
    4: [LEFT, DOWN, UP, RIGHT],
    5: [LEFT, DOWN, CENTER, UP, RIGHT],
    6: [LEFT, DOWN, RIGHT, LEFT, UP, RIGHT],
    7: [LEFT, DOWN, UP, CENTER, DOWN, UP, RIGHT],
    8: [LEFT, DOWN, UP, RIGHT, LEFT, DOWN, UP, RIGHT],
}

# Beat divisor -> colour (1/1, 1/2, 1/3, ...)
SNAP_COLORS = [
    (1, (255, 72, 72)),
    (2, (72, 140, 255)),
    (3, (190, 90, 255)),
    (4, (255, 220, 60)),
    (6, (255, 120, 210)),
    (8, (255, 150, 40)),
    (12, (70, 225, 235)),
    (16, (100, 235, 120)),
]
UNSNAPPED = (170, 170, 185)


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


def arrow_layout(keys: int):
    if keys in ARROW_LAYOUTS:
        return ARROW_LAYOUTS[keys]
    base = [LEFT, DOWN, UP, RIGHT]
    out = [base[i % 4] for i in range(keys)]
    if keys % 2:
        out[keys // 2] = CENTER
    return out


def snap_colors(notes, timing_points):
    """Colour per note based on its position in the beat."""
    if not timing_points:
        return [UNSNAPPED] * len(notes)
    times = [tp[0] for tp in timing_points]
    out = []
    for n in notes:
        i = max(0, bisect.bisect_right(times, n.time) - 1)
        t0, beat = timing_points[i]
        beats = (n.time - t0) / beat
        color = UNSNAPPED
        for div, col in SNAP_COLORS:
            frac = beats * div
            if abs(frac - round(frac)) * beat / div < 2.5:  # within 2.5 ms of the snap
                color = col
                break
        out.append(color)
    return out


def scale_color(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def rounded(w, h, color, radius, alpha=255):
    s = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
    pygame.draw.rect(s, (*color, alpha), (0, 0, w, h), border_radius=radius)
    return s


# ---------- arrow drawing ----------

def _arrow_points(s, inset=0.0):
    """Down-pointing block arrow inside an s x s box, shrunk towards its centre by `inset` (0..1)."""
    pts = [(0.50, 0.96), (0.96, 0.50), (0.68, 0.50), (0.68, 0.05),
           (0.32, 0.05), (0.32, 0.50), (0.04, 0.50)]
    cx, cy = 0.5, 0.55
    k = 1.0 - inset
    return [((cx + (x - cx) * k) * s, (cy + (y - cy) * k) * s) for x, y in pts]


def _diamond_points(s, inset=0.0):
    k = (1.0 - inset) * 0.46
    c = s / 2
    return [(c, c - k * s), (c + k * s, c), (c, c + k * s), (c - k * s, c)]


def _rotate_for(direction, surf):
    angle = {DOWN: 0, LEFT: -90, UP: 180, RIGHT: 90, CENTER: 0}[direction]
    return pygame.transform.rotate(surf, angle) if angle else surf


def make_arrow(size: int, direction: str, fill, outline=(10, 10, 14), shine=True):
    """Anti-aliased arrow sprite, drawn at 4x and scaled down."""
    big = size * 4
    surf = pygame.Surface((big, big), pygame.SRCALPHA)
    shape = _diamond_points if direction == CENTER else _arrow_points
    pygame.draw.polygon(surf, (*outline, 255), shape(big, 0.0))
    pygame.draw.polygon(surf, (*scale_color(fill, 0.72), 255), shape(big, 0.12))
    if shine:
        pygame.draw.polygon(surf, (*scale_color(fill, 1.0), 255), shape(big, 0.30))
        pygame.draw.polygon(surf, (*[min(255, int(v * 0.6 + 255 * 0.4)) for v in fill], 255), shape(big, 0.55))
    surf = _rotate_for(direction, surf)
    return pygame.transform.smoothscale(surf, (size, size))


def make_receptor(size: int, direction: str, pressed: bool, color):
    if pressed:
        spr = make_arrow(size, direction, scale_color(color, 0.75), outline=(235, 235, 245), shine=True)
        small = int(size * 0.9)
        inner = pygame.transform.smoothscale(spr, (small, small))
        spr = pygame.Surface((size, size), pygame.SRCALPHA)
        spr.blit(inner, ((size - small) // 2, (size - small) // 2))
        return spr
    return make_arrow(size, direction, (52, 54, 66), outline=(150, 152, 165), shine=False)


# ---------- built-in skins ----------

class _Builtin:
    keys_under_notes = False
    uses_snap = False

    def __init__(self, scene):
        self.scene = scene
        self.u = u = scene.u
        self.keys = k = scene.keys
        self.colors = column_colors(k)
        w = int(min(100, 520 / k) * u)
        self.col_w = [w] * k
        self.field_w = w * k
        self.field_x = (scene.W - self.field_w) // 2
        self.col_x = [self.field_x + i * w for i in range(k)]
        self._cache = {}
        self.combo_y = int(400 * u)
        self.judge_y = int(560 * u)

        beam_h = int(360 * u)
        self.beam_h = beam_h
        self.beams = []
        for col in self.colors:
            s = pygame.Surface((w, beam_h), pygame.SRCALPHA)
            for y in range(beam_h):
                a = int(90 * (y / beam_h) ** 2.2)
                pygame.draw.line(s, (*col, a), (0, y), (w, y))
            self.beams.append(s)

    def judgement(self, j):
        return None

    def combo(self, n):
        return None

    def stage(self, bg):
        pass

    def _beams(self, surf, pressed, bottom):
        for c in range(self.keys):
            if pressed & (1 << c):
                surf.blit(self.beams[c], (self.col_x[c], bottom - self.beam_h))


class ArrowSkin(_Builtin):
    keys_under_notes = True
    uses_snap = True

    def __init__(self, scene):
        super().__init__(scene)
        w = self.col_w[0]
        self.size = int(w * 0.86)
        self.rc_y = int(860 * self.u)
        self.dirs = arrow_layout(self.keys)
        self.rec_up = [make_receptor(self.size, d, False, self.colors[c]) for c, d in enumerate(self.dirs)]
        self.rec_down = [make_receptor(self.size, d, True, self.colors[c]) for c, d in enumerate(self.dirs)]
        self.flash = [make_arrow(int(self.size * 1.25), d, (255, 255, 255), outline=(255, 255, 255), shine=False)
                      for d in self.dirs]

    def note(self, c, color, dim, hold=False):
        key = (c, color, dim)
        spr = self._cache.get(key)
        if spr is None:
            spr = make_arrow(self.size, self.dirs[c], scale_color(color, 0.35) if dim else color)
            self._cache[key] = spr
        return spr

    def body(self, surf, c, color, top, bottom, state):
        f = {"dead": 0.25, "held": 0.9}.get(state, 0.6)
        bw = int(self.size * 0.5)
        x = self.col_x[c] + (self.col_w[c] - bw) // 2
        if bottom > top:
            pygame.draw.rect(surf, scale_color(color, f), (x, int(top), bw, int(bottom - top)))

    def tail(self, surf, c, color, y, state):
        f = {"dead": 0.25, "held": 0.9}.get(state, 0.6)
        bw = int(self.size * 0.5)
        x = self.col_x[c] + (self.col_w[c] - bw) // 2
        h = int(16 * self.u)
        pygame.draw.rect(surf, scale_color(color, f), (x, int(y - h / 2), bw, h), border_radius=h // 2)

    def receptors(self, surf, pressed):
        self._beams(surf, pressed, self.rc_y + self.size // 2)
        for c in range(self.keys):
            spr = self.rec_down[c] if pressed & (1 << c) else self.rec_up[c]
            surf.blit(spr, (self.col_x[c] + (self.col_w[c] - self.size) // 2, self.rc_y - self.size // 2))

    def effects(self, surf, now, last_hit, rate):
        for c in range(self.keys):
            age = (now - last_hit[c]) / rate
            if 0 <= age < 160:
                k = age / 160
                fl = self.flash[c]
                size = int(fl.get_width() * (0.85 + 0.25 * k))
                spr = pygame.transform.smoothscale(fl, (size, size))
                spr.set_alpha(int(150 * (1 - k)))
                cx = self.col_x[c] + self.col_w[c] // 2
                surf.blit(spr, (cx - size // 2, self.rc_y - size // 2))


class BarSkin(_Builtin):
    def __init__(self, scene):
        super().__init__(scene)
        u = self.u
        self.pad = max(1, int(3 * u))
        self.nw = self.col_w[0] - 2 * self.pad
        self.nh = int(32 * u)
        self.hit_y = int(900 * u)
        self.rc_y = self.hit_y - self.nh // 2
        rh = scene.H - self.hit_y - int(70 * u)
        rad = int(6 * u)
        self.rec_up = [rounded(self.nw, rh, scale_color(c, 0.22), rad) for c in self.colors]
        self.rec_down = [rounded(self.nw, rh, scale_color(c, 0.85), rad) for c in self.colors]
        fh = int(90 * u)
        self.flash_h = fh
        self.flash = []
        for col in self.colors:
            s = pygame.Surface((self.col_w[0], fh), pygame.SRCALPHA)
            for y in range(fh):
                d = abs(y - fh / 2) / (fh / 2)
                pygame.draw.line(s, (*scale_color(col, 1.2), int(200 * (1 - d) ** 2)), (0, y), (self.col_w[0], y))
            self.flash.append(s)

    def stage(self, bg):
        pygame.draw.rect(bg, (230, 230, 240), (self.field_x, self.hit_y, self.field_w, max(2, int(3 * self.u))))

    def note(self, c, color, dim, hold=False):
        key = (c, color, dim)
        spr = self._cache.get(key)
        if spr is None:
            col = scale_color(color, 0.35) if dim else color
            rad = int(6 * self.u)
            spr = rounded(self.nw, self.nh, col, rad)
            if not dim:
                hl = rounded(self.nw - 2 * self.pad, max(2, self.nh // 3), scale_color(col, 1.15), rad // 2)
                hl.set_alpha(120)
                spr.blit(hl, (self.pad, self.pad))
            self._cache[key] = spr
        return spr

    def body(self, surf, c, color, top, bottom, state):
        f = {"dead": 0.25, "held": 0.85}.get(state, 0.55)
        inset = int(self.nw * 0.12)
        if bottom > top:
            pygame.draw.rect(surf, scale_color(color, f),
                             (self.col_x[c] + self.pad + inset, int(top), self.nw - 2 * inset, int(bottom - top)))

    def tail(self, surf, c, color, y, state):
        f = {"dead": 0.25, "held": 0.85}.get(state, 0.55)
        inset = int(self.nw * 0.12)
        h = int(10 * self.u)
        pygame.draw.rect(surf, scale_color(color, f),
                         (self.col_x[c] + self.pad + inset, int(y - h / 2), self.nw - 2 * inset, h),
                         border_radius=int(4 * self.u))

    def receptors(self, surf, pressed):
        self._beams(surf, pressed, self.hit_y)
        for c in range(self.keys):
            spr = self.rec_down[c] if pressed & (1 << c) else self.rec_up[c]
            surf.blit(spr, (self.col_x[c] + self.pad, self.hit_y + int(6 * self.u)))

    def effects(self, surf, now, last_hit, rate):
        for c in range(self.keys):
            age = (now - last_hit[c]) / rate
            if 0 <= age < 140:
                fl = self.flash[c]
                fl.set_alpha(int(255 * (1 - age / 140)))
                surf.blit(fl, (self.col_x[c], self.hit_y - self.flash_h // 2))
