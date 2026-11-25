"""ffmpeg pipeline: renders Scene frames and encodes them with the song audio."""

import os
import subprocess
import time
from pathlib import Path

from .render import RenderOptions, Scene, pygame


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
                fade = max(0.0, min(1.0, (vt - play_seconds) / 0.6))
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
        # Always close ffmpeg's input, otherwise wait() blocks forever after an error.
        if proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {code}")
    return encoder
