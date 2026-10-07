"""Build the display typeface of the dashboard from Michroma (SIL Open Font License 1.1).

    python tools/fonts/make_display_font.py        (needs fonttools)

The widgets were laid out for a wide display face with these proportions: capital
height 0.667 em, ascent 0.673 em, descent 0.327 em, line gap 0.2 em. Michroma is
drawn larger and sits differently in the line. Instead of re-tuning every widget,
this script makes a variant with the proportions the layout expects:

* the glyphs are shown smaller (the em square grows, outlines stay untouched),
* the vertical metrics are set to the values above.

The result is renamed ("GT7C Display"), as is good practice for a modified font.
"""
from pathlib import Path

from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "Michroma-Regular.ttf"
TARGET = HERE.parents[1] / "src/gt7companion/web/static/fonts/GT7CDisplay-Regular.ttf"

CAP_HEIGHT = 0.667                     # of the em, as the layout expects
ASCENT, DESCENT, LINE_GAP = 0.673, 0.327, 0.2
WIN_ASCENT, WIN_DESCENT = 0.87, 0.234
FAMILY = "GT7C Display"


def main() -> None:
    font = TTFont(SOURCE)
    old_upm = font["head"].unitsPerEm
    cap = font["OS/2"].sCapHeight or 1536
    upm = round(cap / CAP_HEIGHT)                       # larger em square = smaller glyphs
    font["head"].unitsPerEm = upm

    hhea, os2 = font["hhea"], font["OS/2"]
    hhea.ascent, hhea.descent, hhea.lineGap = round(ASCENT * upm), -round(DESCENT * upm), round(LINE_GAP * upm)
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = hhea.ascent, hhea.descent, hhea.lineGap
    os2.usWinAscent, os2.usWinDescent = round(WIN_ASCENT * upm), round(WIN_DESCENT * upm)
    os2.fsSelection &= ~(1 << 7)                        # use the hhea/win metrics on every platform

    for record in font["name"].names:
        if record.nameID in (1, 16):
            record.string = FAMILY
        elif record.nameID == 4:
            record.string = f"{FAMILY} Regular"
        elif record.nameID == 6:
            record.string = "GT7CDisplay-Regular"
        elif record.nameID == 3:
            record.string = "GT7CDisplay-Regular;derived from Michroma"
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    font.save(TARGET)
    print(f"{TARGET.name}: em {old_upm} -> {upm}, cap height {cap / upm:.3f} em")


if __name__ == "__main__":
    main()
