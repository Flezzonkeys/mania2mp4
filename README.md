# mania2mp4

Render osu!mania replays (`.osr`) to MP4 videos on Linux.

- Finds the beatmap automatically in your osu! stable `Songs` folder (via the replay's MD5)
- Re-simulates every judgement from the key presses (stable ScoreV1 hit windows, including hold notes); the result is checked against the counts stored in the replay
- **osu! skins**: load any osu! stable skin (`.osk` or folder) with a mania section for the key count: notes, hold bodies and tails, receptors, hit lighting, judgement sprites and combo font
- Built-in skins: **arrow** (notes coloured by rhythm snap: 1/4 red, 1/8 blue, 1/16 yellow, ...) and **bar**
- Clean layout: map card, input card, stats card (accuracy, judgement bars, combo, unstable rate, mean offset) and a hit error card
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

Videos are always saved to `osu-replays` inside your Videos folder (from `xdg-user-dir VIDEOS`, fallback `~/Videos`).

```sh
mania2mp4 "replay.osr"
mania2mp4 *.osr                            # several replays
mania2mp4 replay.osr --scroll-ms 380       # faster scroll speed
mania2mp4 replay.osr -r 2560x1440 --fps 120
mania2mp4 replay.osr --start 60 --duration 10   # quick 10 s preview
mania2mp4 replay.osr --skin bar --colors column  # classic bar notes
mania2mp4 replay.osr --keys "D F J K"      # custom labels for the input overlay
mania2mp4 replay.osr --no-inputs           # hide the input overlay
mania2mp4 --set-flag de                    # small flag next to "Player: name" (de, at, nl, fr, it, ...)
```

Skins:

```sh
mania2mp4 --set-default-skin MySkin.osk   # installs to ~/.local/share/mania2mp4/skins and makes it the default
mania2mp4 --list-skins
mania2mp4 replay.osr --skin arrow          # use another skin just once
mania2mp4 replay.osr --ln-end skin         # long note ends: fade (default), plain or the skin's tail image
```

Run `mania2mp4 --help` for all options (`--offset` for audio sync, `--dim`, `--quality`, `--encoder`, `--beatmap`, `--songs`).

## Limitations

- osu! stable replays. osu!lazer exports work too if you pass the `.osu` file with `--beatmap`.
- Constant scroll speed (scroll velocity changes in the map are ignored).
- No hitsounds yet. osu! skins: stage images, hold lighting (lightingL) and per-column colours from skin.ini are not drawn.
- The in-video combo counts one per note; stable also counts hold ticks, so the final max combo comes from the replay itself.

## License

MIT
