"""Build the label typeface of the "reel" look from Mona Sans (SIL Open Font License 1.1).

    python tools/fonts/make_text_font.py path/to/mona-sans-latin-wght-normal.woff2    (needs fonttools, brotli)

Input is the Latin subset with the weight axis as published by Fontsource
(@fontsource-variable/mona-sans). A subset is a modified version, and the licence of
Mona Sans reserves the name "Mona" for the original – so the file is renamed
("GT7C Text") and nothing else is changed.
"""
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

TARGET = Path(__file__).resolve().parents[2] / "src/gt7companion/web/static/fonts/GT7CText-Variable.woff2"
FAMILY = "GT7C Text"


def main(source: str) -> None:
    font = TTFont(source)
    for record in font["name"].names:
        text = record.toUnicode()
        if record.nameID == 0:
            continue                                   # the copyright notice stays as it is
        if "Mona" in text:
            record.string = (text.replace("Mona Sans", FAMILY).replace("MonaSans", "GT7CText")
                             .replace("Mona", "GT7C"))
    font.flavor = "woff2"
    font.save(TARGET)
    names = {record.nameID: record.toUnicode() for record in font["name"].names}
    print(f"{TARGET.name}: {names.get(1)} / {names.get(6)}")


if __name__ == "__main__":
    main(sys.argv[1])
