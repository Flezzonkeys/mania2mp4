"""Command line interface: mania2mp4 replay.osr [-o out.mp4]"""

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__, judge
from .beatmap import parse_beatmap
from .index import default_songs_dir, find_beatmap
from .inputs import load_key_labels
from .osr import MOD_MR, parse_replay
from .render import RenderOptions, render_video

DEFAULT_REPLAYS = Path.home() / ".local/share/osu-wine/osu!/Replays"
DEFAULT_OUT = Path.home() / "Videos/osu-replays"


def _notify(title, body, gui):
    if gui and shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "mania2mp4", "-i", "video-x-generic", title, body], check=False)


def _pick_replay() -> Path | None:
    if not shutil.which("kdialog"):
        return None
    start = str(DEFAULT_REPLAYS) if DEFAULT_REPLAYS.is_dir() else str(Path.home())
    out = subprocess.run(["kdialog", "--title", "Choose an osu!mania replay", "--getopenfilename",
                          start, "osu! replays (*.osr)"], capture_output=True, text=True)
    path = out.stdout.strip()
    return Path(path) if out.returncode == 0 and path else None


def _safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]+', "", s)
    return re.sub(r"\s+", " ", s).strip()[:150]


def _windows_ticks_to_datetime(ticks: int) -> datetime:
    return datetime(1, 1, 1) + timedelta(microseconds=ticks // 10)


def convert(replay_path: Path, args, gui: bool) -> Path:
    rep = parse_replay(replay_path)
    if rep.mode != 3:
        raise SystemExit(f"{replay_path.name}: not an osu!mania replay (mode {rep.mode}).")

    songs = Path(args.songs) if args.songs else default_songs_dir()
    if args.beatmap:
        bm_path = Path(args.beatmap)
    else:
        if not songs or not songs.is_dir():
            raise SystemExit("Songs folder not found. Pass it with --songs.")
        bm_path = find_beatmap(rep.beatmap_md5, songs)
        if not bm_path:
            raise SystemExit("Beatmap for this replay is not in your Songs folder (was it updated or deleted?). "
                             "Pass the .osu file with --beatmap.")
    bm = parse_beatmap(bm_path)
    if rep.mods & MOD_MR:
        for n in bm.notes:
            n.column = bm.keys - 1 - n.column

    results, win = judge.simulate(bm.notes, rep.frames, bm.keys, bm.od, rep.mods)
    sim = [0] * 6
    for r in results:
        sim[r.judgement] += 1
    expected = [rep.count_geki, rep.count_300, rep.count_katu, rep.count_100, rep.count_50, rep.count_miss]
    print(f"Map:    {bm.artist} - {bm.title} [{bm.version}] ({bm.keys}K, OD {bm.od:g})")
    print(f"Player: {rep.player}  Mods: {rep.mod_string or 'none'}  Score: {rep.score}")
    if sim != expected:
        print(f"Note: re-simulated judgements {sim} differ from the replay {expected}; "
              f"the video shows the simulation.", file=sys.stderr)

    if args.output:
        out = Path(args.output)
        if out.is_dir():
            out = out / _default_name(rep, bm)
    else:
        DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
        out = DEFAULT_OUT / _default_name(rep, bm)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.keys:
        labels = args.keys.split()
        if len(labels) != bm.keys:
            raise SystemExit(f"--keys needs {bm.keys} labels for this map, got {len(labels)}.")
    else:
        labels = load_key_labels(songs, bm.keys)

    w, h = (int(x) for x in args.resolution.lower().split("x"))
    opts = RenderOptions(width=w, height=h, fps=args.fps, scroll_ms=args.scroll_ms, bg_dim=args.dim,
                         encoder=args.encoder, quality=args.quality, offset_ms=args.offset,
                         start_ms=args.start * 1000 if args.start is not None else None,
                         duration_s=args.duration, skin=args.skin, colors=args.colors,
                         show_inputs=not args.no_inputs, key_labels=labels)

    def progress(done, total, elapsed, encoder):
        pct = done / total
        fps = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / fps if fps > 0 else 0
        bar = "#" * int(pct * 30)
        sys.stdout.write(f"\r[{bar:<30}] {pct * 100:5.1f}%  {fps:5.0f} fps  ETA {eta:4.0f}s  ({encoder})")
        sys.stdout.flush()

    _notify("Rendering replay", f"{bm.title} [{bm.version}]", gui)
    render_video(bm, rep, results, win, out, opts, progress=progress)
    print(f"\nSaved: {out}")
    return out


def _default_name(rep, bm) -> str:
    date = _windows_ticks_to_datetime(rep.timestamp).strftime("%Y-%m-%d")
    mods = f" +{rep.mod_string}" if rep.mod_string else ""
    return _safe_name(f"{rep.player} - {bm.artist} - {bm.title} [{bm.version}]{mods} ({date})") + ".mp4"


def main(argv=None):
    p = argparse.ArgumentParser(prog="mania2mp4", description="Render osu!mania replays (.osr) to MP4 videos.")
    p.add_argument("replays", nargs="*", help=".osr files (opens a file picker if empty)")
    p.add_argument("-o", "--output", help="output file or folder (default ~/Videos/osu-replays)")
    p.add_argument("--beatmap", help="path to the .osu file (skips the automatic lookup)")
    p.add_argument("--songs", help="osu! Songs folder (auto-detected by default)")
    p.add_argument("--scroll-ms", type=float, default=450, help="time in ms a note is visible before it hits (lower = faster, default 450)")
    p.add_argument("--skin", choices=["arrow", "bar"], default="arrow", help="note style (default arrow)")
    p.add_argument("--colors", choices=["snap", "column"],
                   help="note colours: by rhythm (snap, default for arrows) or by column (default for bars)")
    p.add_argument("--no-inputs", action="store_true", help="hide the keyboard input overlay")
    p.add_argument("--keys", help='key labels for the input overlay, e.g. "D F J K" (default: read from osu! config)')
    p.add_argument("-r", "--resolution", default="1920x1080", help="video size, e.g. 1280x720 or 2560x1440")
    p.add_argument("--fps", type=int, default=60)
    p.add_argument("--dim", type=float, default=0.8, help="background dim 0..1 (default 0.8)")
    p.add_argument("--encoder", choices=["auto", "vaapi", "x264"], default="auto")
    p.add_argument("--quality", type=int, default=20, help="lower = better quality and bigger file (default 20)")
    p.add_argument("--offset", type=float, default=0, help="audio offset in ms (positive = audio later)")
    p.add_argument("--start", type=float, help="start at this map time in seconds (preview)")
    p.add_argument("--duration", type=float, help="only render this many seconds (preview)")
    p.add_argument("--gui", action="store_true", help="desktop notifications (used by the menu entry)")
    p.add_argument("--version", action="version", version=f"mania2mp4 {__version__}")
    args = p.parse_args(argv)

    replays = [Path(r) for r in args.replays]
    gui = args.gui
    if not replays:
        picked = _pick_replay()
        if not picked:
            p.print_usage()
            return 1
        replays = [picked]
        gui = True

    failed = 0
    for path in replays:
        try:
            out = convert(path, args, gui)
            _notify("Replay rendered", out.name, gui)
        except (SystemExit, Exception) as exc:  # noqa: BLE001
            failed += 1
            msg = str(exc) or exc.__class__.__name__
            print(f"\nError: {msg}", file=sys.stderr)
            _notify("Rendering failed", msg, gui)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
