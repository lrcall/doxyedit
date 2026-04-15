"""Check all themes meet minimum contrast ratios.

Light themes (bg luminance > 0.5):
  text_primary vs bg_main   ≥ 7:1  (WCAG AAA normal text)
  text_secondary vs bg_main ≥ 4.5:1 (WCAG AA normal text)
  text_muted vs bg_main     ≥ 3:1  (WCAG AA large text / UI components)

Dark themes (bg luminance ≤ 0.5):
  Same ratios — the formula is symmetric.

Mid themes (bg luminance 0.3–0.5):
  Same ratios — they just tend to pass more easily.

Usage: python scripts/check_theme_contrast.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from doxyedit.themes import THEMES


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def relative_luminance(r: float, g: float, b: float) -> float:
    """WCAG 2.1 relative luminance."""
    def linearize(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = relative_luminance(*hex_to_rgb(hex1))
    l2 = relative_luminance(*hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# Minimum contrast requirements
CHECKS = [
    ("text_primary",   "bg_main",   7.0,   "AAA normal text"),
    ("text_primary",   "bg_raised", 7.0,   "AAA normal text"),
    ("text_secondary", "bg_main",   4.5,   "AA normal text"),
    ("text_muted",     "bg_main",   3.0,   "AA large text / UI"),
    ("text_on_accent", "accent",    4.5,   "AA text on accent"),
    ("statusbar_text", "statusbar_bg", 4.5, "AA statusbar"),
]

# Additional pairs to check
EXTRA_CHECKS = [
    ("text_primary",   "bg_input",  7.0,   "AAA input text"),
    ("text_secondary", "bg_raised", 4.5,   "AA raised text"),
    ("text_muted",     "bg_raised", 3.0,   "AA muted on raised"),
]


def main():
    all_passed = True
    for tid, theme in THEMES.items():
        bg_lum = relative_luminance(*hex_to_rgb(theme.bg_main))
        kind = "light" if bg_lum > 0.5 else ("mid" if bg_lum > 0.2 else "dark")
        fails = []
        for fg_attr, bg_attr, min_ratio, label in CHECKS + EXTRA_CHECKS:
            fg = getattr(theme, fg_attr, "")
            bg = getattr(theme, bg_attr, "")
            if not fg or not bg:
                continue
            ratio = contrast_ratio(fg, bg)
            if ratio < min_ratio:
                fails.append((fg_attr, bg_attr, ratio, min_ratio, label))

        if fails:
            all_passed = False
            print(f"\n{'FAIL':>6}  {tid} ({kind}, bg_main={theme.bg_main})")
            for fg_attr, bg_attr, ratio, min_ratio, label in fails:
                fg_val = getattr(theme, fg_attr)
                bg_val = getattr(theme, bg_attr)
                print(f"        {fg_attr} ({fg_val}) vs {bg_attr} ({bg_val}): "
                      f"{ratio:.1f}:1 < {min_ratio}:1 [{label}]")
        else:
            print(f"  PASS  {tid} ({kind})")

    print()
    if all_passed:
        print("All themes pass contrast checks.")
    else:
        print("Some themes FAIL — fix the values above.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
