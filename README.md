# mania2mp4

Render osu!mania replays (`.osr`) to MP4 videos on Linux.

- Finds the beatmap automatically in your osu! stable `Songs` folder (via the replay's MD5)
- Re-simulates every judgement from the key presses (stable ScoreV1 hit windows, including hold notes); the result is checked against the counts stored in the replay
- Two skins: **arrow** (default, notes coloured by rhythm snap: 1/4 red, 1/8 blue, 1/16 yellow, ...) and **bar**
- Keyboard input overlay with your real key bindings (read from `osu!.<user>.cfg`), key rain, press counters and KPS
- Live accuracy, judgement counts, combo, hit error bar, key lights and a results screen
- Blurred map background, song audio with DT/NC/HT handled
- Fast: frames are drawn with pygame and piped into ffmpeg, using VAAPI hardware encoding when available (about 5x realtime at 1080p60)

## Requirements

`python` (3.10+), `python-pygame`, `python-pillow`, `ffmpeg`. Optional: `kdialog` and `notify-send` for the file picker and notifications.

## Install

```sh
./install.sh
```

This adds the `mania2mp4` command to `~/.local/bin`, an app menu entry and a "Convert to MP4" action when you right-click an `.osr` file in Dolphin.

## Usage

```sh
mania2mp4 "replay.osr"                     # saves to ~/Videos/osu-replays
mania2mp4 *.osr -o ~/Videos                # several replays
mania2mp4 replay.osr --scroll-ms 380       # faster scroll speed
mania2mp4 replay.osr -r 2560x1440 --fps 120
mania2mp4 replay.osr --start 60 --duration 10   # quick 10 s preview
mania2mp4 replay.osr --skin bar --colors column  # classic bar notes
mania2mp4 replay.osr --keys "D F J K"      # custom labels for the input overlay
mania2mp4 replay.osr --no-inputs           # hide the input overlay
```

Run `mania2mp4 --help` for all options (`--offset` for audio sync, `--dim`, `--quality`, `--encoder`, `--beatmap`, `--songs`).

## Limitations

- osu! stable replays. osu!lazer exports work too if you pass the `.osu` file with `--beatmap`.
- Constant scroll speed (scroll velocity changes in the map are ignored).
- No hitsounds and no osu! skin (.ini) support yet.
- The in-video combo counts one per note; stable also counts hold ticks, so the final max combo comes from the replay itself.

## License

MIT
