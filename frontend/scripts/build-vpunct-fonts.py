# Rebuilds static/fonts/beepub-vpunct-{serif,sans}.woff2 — the vertical-
# punctuation subsets injected into reader iframes (see EpubReader.svelte,
# VPUNCT_RANGE). Run with:
#   uv run --with fonttools --with brotli python scripts/build-vpunct-fonts.py \
#     <NotoSerifCJKtc-Regular.otf> <NotoSansCJKtc-Regular.otf>
#
# Two deliberate deviations from a plain pyftsubset run:
# - Only characters whose Noto glyphs have vert alternates are included
#   (— U+2014 and － U+FF0D don't; including them would claim the char
#   and render it unrotated).
# - hhea/OS-2 metrics are overwritten with iOS PingFang's values: Safari
#   aligns cross-font runs in vertical text on a central baseline derived
#   from ascent/descent (BASE is ignored), and the running CJK text these
#   glyphs mix into on iOS is always PingFang. Stock Noto metrics leave
#   the punctuation visibly off-axis (~7% em to the right).
import subprocess
import sys
import tempfile

from fontTools.ttLib import TTFont

UNICODES = "2015,2026,3008-3011,3014-301F,FF08-FF09,FF3B,FF3D,FF5B,FF5D,FF5E"
OUT = {"serif": "static/fonts/beepub-vpunct-serif.woff2", "sans": "static/fonts/beepub-vpunct-sans.woff2"}

for src, kind in zip(sys.argv[1:3], ("serif", "sans")):
    with tempfile.NamedTemporaryFile(suffix=".woff2") as tmp:
        subprocess.run(
            [
                sys.executable, "-m", "fontTools.subset", src,
                f"--unicodes={UNICODES}",
                "--layout-features+=vert,vrt2",
                "--flavor=woff2",
                f"--output-file={tmp.name}",
            ],
            check=True,
        )
        font = TTFont(tmp.name)
    hhea, os2 = font["hhea"], font["OS/2"]
    hhea.ascent, hhea.descent = 1060, -340
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = 860, -140, 0
    os2.usWinAscent, os2.usWinDescent = 1060, 340
    if "BASE" in font:
        del font["BASE"]
    font.flavor = "woff2"
    font.save(OUT[kind])
    print("wrote", OUT[kind])
