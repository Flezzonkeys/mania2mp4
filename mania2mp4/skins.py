"""Note skins: sprite generation for bar and arrow styles, plus rhythm (snap) colouring."""

import bisect

import pygame

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
    ss = 4
    big = size * ss
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
        fill = scale_color(color, 0.75)
        outline = (235, 235, 245)
    else:
        fill = (52, 54, 66)
        outline = (150, 152, 165)
    spr = make_arrow(size, direction, fill, outline=outline, shine=pressed)
    if pressed:
        small = int(size * 0.9)
        inner = pygame.transform.smoothscale(spr, (small, small))
        spr = pygame.Surface((size, size), pygame.SRCALPHA)
        spr.blit(inner, ((size - small) // 2, (size - small) // 2))
    return spr
