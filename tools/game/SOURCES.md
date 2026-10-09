# Sources of the game's assets

The little game "Tisch Turismo" (`src/gt7companion/web/static/game/`) loads its models, textures and
bitmap fonts from `assets/` beside its code. Everything in there is made by the scripts in this
folder, so the repository holds the sources of what it ships. Below, `assets/` means
`src/gt7companion/web/static/game/assets/`.

## What makes what

| Script | Makes | Needs |
|---|---|---|
| `make_textures.py` | `assets/tex/*.png`, 11 textures, drawn by the script | numpy, Pillow |
| `make_fonts.py` | `assets/fonts/hud.png`, `hud.json`, `hand.png`, `hand.json` | numpy, Pillow, the typefaces in `fonts/` |
| `blender/make_track_kit.py` | `assets/models/track_kit.glb` (track piece, kerb, start arch) | Blender |
| `blender/make_props.py` | `assets/models/props.glb` (13 desk props) | Blender |
| `blender/make_desk_extras.py` | `assets/models/desk_extras.glb` (10 more desk objects) | Blender |
| `blender/make_r34.py` | `assets/models/r34.glb` (the toy car) | Blender and the original model, which is not in this repository (see below) |

`blender/kit_common.py`, `blender/kit_preview.py` and `blender/r34_shape.py` are parts of these
scripts, not scripts of their own. The first lines of every script say what it takes and what it
gives; the Blender scripts also state the contract between their file and the game.

## Running

```sh
.venv/bin/python tools/game/make_textures.py [--out DIR] [--sheet DIR]
.venv/bin/python tools/game/make_fonts.py [--out DIR] [--sheets DIR]
"/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
    -P tools/game/blender/make_track_kit.py -- [--out-dir DIR] [--work-dir DIR] [--preview DIR]
```

Without switches a script writes straight into `assets/` and replaces the shipped file; `--out` /
`--out-dir` writes somewhere else instead. Contact and proof sheets, preview images and Blender
working files (`.blend`) are written only into a folder you name with `--sheet`, `--sheets`,
`--preview` or `--work-dir`. The Blender scripts were written for Blender 5.1.1; the shipped
models carry the exporter tag "Khronos glTF Blender I/O v5.1.19".

## Fonts

The two bitmap fonts are rasterised from freely licensed typefaces (SIL Open Font License 1.1).
The originals and their licence texts are in `fonts/`; the licence texts are the same files as in
`assets/fonts/` (upstream they are called `OFL.txt`). The licence is also stated in the name table
of both font files.

| Atlas | Typeface | Author and notice | Source |
|---|---|---|---|
| `hud.png`, `hud.json` | Press Start 2P Regular, version 3.000 | CodeMan38; "Copyright 2012 The Press Start 2P Project Authors, with Reserved Font Name "Press Start 2P"" | https://github.com/google/fonts/tree/main/ofl/pressstart2p |
| `hand.png`, `hand.json` | Kalam Regular, version 2.001 | Indian Type Foundry (Lipi Raval, Jonny Pinhorn); "Copyright (c) 2014, Indian Type Foundry" | https://github.com/google/fonts/tree/main/ofl/kalam |

The full notices are the first lines of the two licence texts. Downloaded on 8 October 2026 from
the Google Fonts repository on GitHub (branch `main`):

| File in `fonts/` | Address | SHA-256 |
|---|---|---|
| `PressStart2P-Regular.ttf` | https://raw.githubusercontent.com/google/fonts/main/ofl/pressstart2p/PressStart2P-Regular.ttf | `034c77f1f05ec89421e4a63f0e3a4ca1ecf852cc6d2bf611f126f275728e017d` |
| `PressStart2P-OFL.txt` | https://raw.githubusercontent.com/google/fonts/main/ofl/pressstart2p/OFL.txt | – |
| `Kalam-Regular.ttf` | https://raw.githubusercontent.com/google/fonts/main/ofl/kalam/Kalam-Regular.ttf | `57cecb63d4608019371954274ae1d8c397764debd5b19d4a33c1efa4dc923c0b` |
| `Kalam-OFL.txt` | https://raw.githubusercontent.com/google/fonts/main/ofl/kalam/OFL.txt | – |

What was made of them:

- `hud`: Press Start 2P at its native size of 8 pixels, without anti-aliasing, otherwise unchanged.
- `hand`: Kalam Regular at 11 pixels, without anti-aliasing. These characters were redrawn by hand,
  pixel by pixel, because their shape merged at this size (`HAND_PATCHES` in `make_fonts.py`):
  `a h i j l m n u w x`, `A S W`, `1 5 8`, `Ä Ö Ü ä`, and `! " % * × … „ “`.

The atlases are derived works and are under the SIL Open Font License 1.1 like the originals. They
carry names of their own ("hud", "hand"); the Reserved Font Name "Press Start 2P" is not used for
the derived version. Whoever passes the game on passes on the two licence texts too.

The lettering in `assets/tex/titel.png` uses neither typeface: its letters are drawn in
`make_textures.py`.

## The toy car

`assets/models/r34.glb` was rebuilt by script from measurements of the Sketchfab model
"TOON Japan : Nissan Skyline R34" by LePoint_BAT, licence
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):
https://sketchfab.com/3d-models/toon-japan-nissan-skyline-r34-30c3e10eeed64f30b65786bc3ca9cbdb

The shape is a hand-placed cage of vertices measured on the original (`blender/r34_shape.py`). The
script `blender/make_r34.py` takes scale, axle positions, track, wheel size and the painting of the
texture from the original at every run, and checks that the cage lies on the original's skin. So it
cannot run without the original, and **the original model itself is not part of this repository**.
To run the script, download the model from the address above, save it as a Blender file named
`tools/game/source/Nissan Skyline R34.blend` (that folder is ignored by git; `--source FILE` names
another file) and start Blender with `--disable-autoexec`, as the file comes from the internet.
Without the file the script stops at once and says so.

## Checked

On 9 October 2026, `make_textures.py` and `make_fonts.py` (Python 3.14, Pillow 12.3.0 with
FreeType 2.14.3, numpy 2.5.3) wrote all 11 textures and all 4 font files byte for byte as they are in
the repository, and `make_track_kit.py` (Blender 5.1.1) wrote a byte-identical `track_kit.glb`.
`make_props.py`, `make_desk_extras.py` and `make_r34.py` were also run with Blender 5.1.1,
writing to a separate folder; their three GLBs were byte-identical to the shipped models.
The car generator read the original model with `--disable-autoexec`.
A different Pillow or Blender version may change bytes without changing the pictures or models.
