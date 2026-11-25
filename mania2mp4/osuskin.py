"""osu! stable skin support (.osk archives or skin folders) for osu!mania."""

import os
import re
import zipfile
from pathlib import Path

import pygame

from .judge import J50, J100, J200, J300, MAX, MISS

SKIN_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "mania2mp4" / "skins"


class SkinError(Exception):
    pass


# ---------- installing and finding skins ----------

def install_osk(osk: Path) -> Path:
    """Extract an .osk into the skin folder (safe against path traversal). Returns the skin folder."""
    target = SKIN_DIR / osk.stem
    if target.is_dir() and any(target.iterdir()):
        return target
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(osk) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or not name.strip("/"):
                continue
            dest = (target / name).resolve()
            if root not in dest.parents:
                continue  # skip entries that would land outside the skin folder
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
    return target


def installed_skins():
    if not SKIN_DIR.is_dir():
        return []
    return sorted(p.name for p in SKIN_DIR.iterdir() if p.is_dir())


def resolve_skin_dir(spec: str) -> Path | None:
    """spec: path to .osk, path to a skin folder, or the name of an installed skin."""
    p = Path(spec).expanduser()
    if p.is_file() and p.suffix.lower() == ".osk":
        return install_osk(p)
    if p.is_dir():
        return p
    if (SKIN_DIR / spec).is_dir():
        return SKIN_DIR / spec
    lowered = spec.lower()
    for name in installed_skins():
        if name.lower() == lowered:
            return SKIN_DIR / name
    return None


# ---------- skin.ini ----------

def _parse_ini(path: Path):
    sections = []  # list of (name, dict)
    current = None
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"\[(.+)\]", line)
        if m:
            current = (m.group(1).strip(), {})
            sections.append(current)
            continue
        if current is None or ":" not in line:
            continue
        k, v = line.split(":", 1)
        current[1][k.strip()] = v.strip()
    return sections


def _default_note_index(keys: int, c: int) -> str:
    """osu! default naming: outer columns '1', inner '2', middle of odd counts 'S'."""
    if keys % 2 and c == keys // 2:
        return "S"
    half = c if c < keys / 2 else keys - 1 - c
    return "1" if half % 2 == 0 else "2"


class _Files:
    """Case-insensitive file lookup inside a skin folder (skins come from Windows)."""

    def __init__(self, root: Path):
        self.map = {}
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                full = Path(dirpath) / f
                self.map[str(full.relative_to(root)).replace("\\", "/").lower()] = full

    def image(self, name: str):
        """Return (path, is_2x) for an image name without extension, preferring @2x."""
        base = name.replace("\\", "/").strip().lower()
        if base.endswith(".png"):
            base = base[:-4]
        for suffix, is2x in (("@2x.png", True), (".png", False)):
            p = self.map.get(base + suffix)
            if p:
                return p, is2x
        return None, False


def _native(surf):
    """Copy into a standard 32-bit ARGB surface so blits need no per-frame conversion."""
    out = pygame.Surface(surf.get_size(), pygame.SRCALPHA, 32)
    out.blit(surf, (0, 0))
    return out


def _load(path):
    return _native(pygame.image.load(str(path)))


def _premultiplied(surf):
    """Copy for additive blending: colours multiplied by alpha, alpha dropped."""
    out = surf.copy()
    alpha = pygame.surfarray.pixels_alpha(out)
    rgb = pygame.surfarray.pixels3d(out)
    rgb[:] = (rgb.astype("uint16") * alpha[..., None] // 255).astype("uint8")
    del rgb, alpha
    result = pygame.Surface(out.get_size(), 0, 32)
    result.blit(out, (0, 0))
    return result


def _darken(surf, f=0.4):
    out = surf.copy()
    v = int(255 * f)
    out.fill((v, v, v, 255), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def _scale_w(surf, width):
    h = max(1, round(surf.get_height() * width / surf.get_width()))
    return _native(pygame.transform.smoothscale(surf, (width, h)))


class OsuSkin:
    uses_snap = False

    def __init__(self, scene, skin_dir: Path):
        self.scene = scene
        H = scene.H
        k = self.keys = scene.keys
        ini = skin_dir / "skin.ini"
        files = _Files(skin_dir)
        if "skin.ini" in files.map:
            ini = files.map["skin.ini"]
        sections = _parse_ini(ini) if ini.is_file() else []
        general = next((d for n, d in sections if n == "General"), {})
        fonts = next((d for n, d in sections if n == "Fonts"), {})
        mania = next((d for n, d in sections if n == "Mania" and d.get("Keys") == str(k)), None)
        if mania is None:
            raise SkinError(f"skin has no osu!mania {k}K section")
        self.name = general.get("Name", skin_dir.name)

        s = H / 480.0
        widths = [float(x) for x in mania.get("ColumnWidth", "30").split(",") if x.strip()]
        widths = (widths + [widths[-1]] * k)[:k]
        self.col_w = [max(8, int(w * s)) for w in widths]
        self.field_w = sum(self.col_w)
        self.field_x = (scene.W - self.field_w) // 2
        self.col_x = []
        x = self.field_x
        for w in self.col_w:
            self.col_x.append(x)
            x += w
        hit_y = float(mania.get("HitPosition", "402")) * s
        self.keys_under_notes = mania.get("KeysUnderNotes", "0") == "1"
        self.judgement_line = mania.get("JudgementLine", "1") == "1"
        self.hit_y = int(hit_y)
        self.judge_y = int(float(mania.get("ScorePosition", "240")) * s)
        self.combo_y = int(float(mania.get("ComboPosition", "180")) * s)

        def img(key, default):
            name = mania.get(key, default)
            path, is2x = files.image(name)
            if not path and name != default:
                path, is2x = files.image(default)
            return _load(path) if path else None

        self.notes, self.heads, self.bodies, self.tails = [], [], [], []
        self.keys_up, self.keys_down = [], []
        for c in range(k):
            d = _default_note_index(k, c)
            note = img(f"NoteImage{c}", f"mania-note{d}")
            if note is None:
                raise SkinError(f"note image for column {c + 1} not found")
            w = self.col_w[c]
            note = _scale_w(note, w)
            head = img(f"NoteImage{c}H", f"mania-note{d}H")
            head = _scale_w(head, w) if head else note
            body = img(f"NoteImage{c}L", f"mania-note{d}L")
            tail = img(f"NoteImage{c}T", f"mania-note{d}T")
            ku = img(f"KeyImage{c}", f"mania-key{d}")
            kd = img(f"KeyImage{c}D", f"mania-key{d}D")
            self.notes.append((note, _darken(note)))
            self.heads.append((head, _darken(head)))
            self.bodies.append((_scale_w(body, w), _darken(_scale_w(body, w))) if body else None)
            self.tails.append((_scale_w(tail, w), _darken(_scale_w(tail, w))) if tail else None)
            self.keys_up.append(self._cropped(_scale_w(ku, w)) if ku else None)
            self.keys_down.append(self._cropped(_scale_w(kd, w)) if kd else None)

        # Plain hold end: close the body with an edge matching its side borders instead of the skin's tail image
        ln_end = getattr(scene.o, "ln_end", "fade")
        self.plain_end = ln_end == "plain"
        self.fade_end = ln_end == "fade"
        # Fade end: the top part of the body image with an alpha ramp (transparent at the tail)
        self.fade_len = int(self.col_w[0] * 0.6)
        self.fade_caps = []
        for c in range(k):
            b = self.bodies[c]
            if not b:
                self.fade_caps.append(None)
                continue
            pair = []
            for img in b:
                cap = _native(pygame.transform.scale(img, (img.get_width(), self.fade_len)))
                alpha = pygame.surfarray.pixels_alpha(cap)
                for yy in range(self.fade_len):
                    alpha[:, yy] = (alpha[:, yy].astype("float32") * (yy / self.fade_len) ** 1.3).astype("uint8")
                del alpha
                pair.append(cap)
            self.fade_caps.append(pair)
        self.end_caps = []
        for c in range(k):
            b = self.bodies[c]
            if not b:
                self.end_caps.append(None)
                continue
            r = b[0].get_bounding_rect()
            t = max(2, round(self.col_w[c] * 3 / 140))
            caps = []
            for alpha in (191, 70):
                cap = pygame.Surface((max(1, r.width), t), pygame.SRCALPHA, 32)
                pygame.draw.rect(cap, (255, 255, 255, alpha), cap.get_rect(), border_radius=t)
                caps.append(cap)
            self.end_caps.append((r.x, caps))

        # Note centre sits on the receptor when its bottom edge reaches HitPosition.
        self.rc_y = self.hit_y - self.notes[0][0].get_height() // 2

        # Hit lighting animation (lightingN-0, -1, ...), additive.
        self.lighting = []
        i = 0
        while True:
            path, _ = files.image(f"lightingN-{i}")
            if not path:
                break
            self.lighting.append(_load(path))
            i += 1
        if not self.lighting:
            path, _ = files.image("lightingN")
            if path:
                self.lighting.append(_load(path))
        if self.lighting:
            bbox = None
            for fr in self.lighting:
                r = fr.get_bounding_rect()
                if r.width:
                    bbox = r if bbox is None else bbox.union(r)
            bbox = bbox or self.lighting[0].get_rect()
            scale = 1.1 * min(self.col_w) / max(1, bbox.width)
            frames = []
            for fr in self.lighting:
                size = (max(1, int(fr.get_width() * scale)), max(1, int(fr.get_height() * scale)))
                frames.append(_premultiplied(pygame.transform.smoothscale(fr, size)))
            self.lighting = frames
            self.light_center = (bbox.centerx * scale, bbox.centery * scale)

        # Judgements (sprite scale: osu! gameplay sprites are sized for 768 px height)
        gscale = H / 768.0
        self.judge_sprites = {}
        for j, name in ((MAX, "mania-hit300g"), (J300, "mania-hit300"), (J200, "mania-hit200"),
                        (J100, "mania-hit100"), (J50, "mania-hit50"), (MISS, "mania-hit0")):
            path, is2x = files.image(name)
            if not path:
                continue
            spr = _load(path)
            f = gscale / (2 if is2x else 1)
            self.judge_sprites[j] = pygame.transform.smoothscale(
                spr, (max(1, int(spr.get_width() * f)), max(1, int(spr.get_height() * f))))

        # Combo digits
        prefix = fonts.get("ComboPrefix", "score").replace("\\", "/")
        self.digits = {}
        for dch in "0123456789":
            path, is2x = files.image(f"{prefix}-{dch}")
            if not path:
                self.digits = {}
                break
            spr = _load(path)
            f = gscale * 1.25 / (2 if is2x else 1)
            self.digits[dch] = pygame.transform.smoothscale(
                spr, (max(1, int(spr.get_width() * f)), max(1, int(spr.get_height() * f))))
        self._combo_cache = {}

    @staticmethod
    def _cropped(img):
        """(sprite cropped to its visible pixels, y offset of the crop inside the full image, full height)."""
        r = img.get_bounding_rect()
        if r.height == 0:
            return None
        return img.subsurface((0, r.y, img.get_width(), r.height)).copy(), r.y, img.get_height()

    # ----- interface used by the scene -----

    def stage(self, bg):
        if self.judgement_line:
            pygame.draw.rect(bg, (220, 220, 230), (self.field_x, self.hit_y, self.field_w, 2))

    def note(self, c, color, dim, hold=False):
        pair = self.heads[c] if hold else self.notes[c]
        return pair[1] if dim else pair[0]

    def body(self, surf, c, color, top, bottom, state):
        if bottom <= top or not self.bodies[c]:
            return
        i = 1 if state == "dead" else 0
        img = self.bodies[c][i]
        h = int(bottom - top)
        if h < 1:
            return
        x, top = self.col_x[c], int(top)
        if self.fade_end and self.fade_caps[c]:
            cap = self.fade_caps[c][i]
            # Fade over at most 45 % of the body so short notes keep a solid part
            fl = min(self.fade_len, int(h * 0.45))
            if fl >= 2:
                if fl != self.fade_len:
                    cap = pygame.transform.scale(cap, (cap.get_width(), fl))
                surf.blit(cap, (x, top))
                top += fl
                h -= fl
        surf.blit(pygame.transform.scale(img, (img.get_width(), h)), (x, top))

    def tail(self, surf, c, color, y, state):
        if self.fade_end:
            return
        if self.plain_end and self.end_caps[c]:
            x_off, caps = self.end_caps[c]
            surf.blit(caps[1 if state == "dead" else 0], (self.col_x[c] + x_off, int(y)))
            return
        if not self.tails[c]:
            return
        img = self.tails[c][1 if state == "dead" else 0]
        surf.blit(img, (self.col_x[c], int(y - img.get_height() / 2)))

    def receptors(self, surf, pressed):
        H = self.scene.H
        for c in range(self.keys):
            entry = self.keys_down[c] if pressed & (1 << c) and self.keys_down[c] else self.keys_up[c]
            if entry:
                img, off, full_h = entry
                surf.blit(img, (self.col_x[c], H - full_h + off))

    def effects(self, surf, now, last_hit, rate):
        if not self.lighting:
            return
        frame_ms = 18
        n = len(self.lighting)
        for c in range(self.keys):
            age = (now - last_hit[c]) / rate
            if 0 <= age < frame_ms * n:
                fr = self.lighting[int(age // frame_ms)]
                cx = self.col_x[c] + self.col_w[c] / 2
                surf.blit(fr, (int(cx - self.light_center[0]), int(self.rc_y - self.light_center[1])),
                          special_flags=pygame.BLEND_RGB_ADD)

    def judgement(self, j):
        return self.judge_sprites.get(j)

    def combo(self, n):
        if not self.digits:
            return None
        spr = self._combo_cache.get(n)
        if spr is None:
            parts = [self.digits[ch] for ch in str(n)]
            w = sum(p.get_width() for p in parts)
            h = max(p.get_height() for p in parts)
            spr = pygame.Surface((w, h), pygame.SRCALPHA)
            x = 0
            for p in parts:
                spr.blit(p, (x, 0))
                x += p.get_width()
            if len(self._combo_cache) > 600:
                self._combo_cache.clear()
            self._combo_cache[n] = spr
        return spr
