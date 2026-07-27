#!/usr/bin/env python3
"""
pixart.py — Pixel-density ASCII / Unicode art converter

Each output character represents the average brightness of a pixel
block from the source image.  Optional Floyd-Steinberg dithering
distributes quantisation error to neighbouring cells, preserving
local average brightness even with very short character ramps.

Usage:
    python pixart.py <image>
    python pixart.py <image> -w 80 -c blocks --dither
"""

import argparse
import sys
from PIL import Image

# Ensure stdout/stderr use UTF-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Terminal char aspect: chars are ~2× taller than wide.
# We sample at double vertical resolution so circles stay circular.
CHAR_RATIO = 2.0

# ---- Character ramps (dark → light) ----
RAMPS = {
    "detailed":  "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`'. ",
    "blocks":    "█▓▒░ ",
    "minimal":   "#. ",
    "ascii":     "@%#*+=-:. ",
}


def get_ramp(name="detailed"):
    """Get character ramp by name."""
    return RAMPS.get(name, RAMPS["detailed"])


# ── Floyd-Steinberg dithering ─────────────────────────────

def floyd_steinberg(grid, ramp_len):
    """
    Apply Floyd-Steinberg error diffusion in-place on a 2D luminance grid.

    Parameters
    ----------
    grid : list[list[float]]
        2D array of luminance values (0–255), shape (height, width).
        Modified in place: each cell becomes the quantised value
        that will be mapped to a character.
    ramp_len : int
        Number of discrete output levels (ramp length).
    """
    h, w = len(grid), len(grid[0])
    step = 255.0 / (ramp_len - 1) if ramp_len > 1 else 255.0

    for y in range(h):
        row = grid[y]
        for x in range(w):
            old = row[x]
            # Quantise to nearest level
            idx = int(round(old / step))
            idx = max(0, min(ramp_len - 1, idx))
            new = idx * step
            row[x] = new

            error = old - new

            # Distribute error to unprocessed neighbours
            # [x+1, y]     ← 7/16
            # [x-1, y+1]   ← 3/16
            # [x,   y+1]   ← 5/16
            # [x+1, y+1]   ← 1/16
            if x + 1 < w:
                grid[y][x + 1] += error * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    grid[y + 1][x - 1] += error * 3 / 16
                grid[y + 1][x] += error * 5 / 16
                if x + 1 < w:
                    grid[y + 1][x + 1] += error * 1 / 16


# ── Core conversion ───────────────────────────────────────

def convert_image(image_path, width=80, height=0, char_set="detailed",
                  invert=False, contrast=1.0, brightness=0, dither=False):
    """
    Convert image to character art.

    Parameters
    ----------
    image_path : str
        Path to input image.
    width : int
        Output character width.
    height : int
        Output character height (0 = auto from aspect ratio).
    char_set : str
        Ramp name (classic, detailed, blocks, minimal, ascii).
    invert : bool
        Swap dark/light mapping.
    contrast : float
        Contrast multiplier (0.5 … 3.0).
    brightness : int
        Brightness offset (-128 … 128).
    dither : bool
        Enable Floyd-Steinberg error diffusion.

    Returns
    -------
    (art_str, actual_width, actual_height)
    """
    img = Image.open(image_path).convert("RGBA")
    img_w, img_h = img.size

    # Auto height (preserve aspect ratio with font compensation)
    if height == 0:
        height = max(1, int(img_h / img_w * width / CHAR_RATIO))

    ramp = get_ramp(char_set)
    ramp_len = len(ramp)

    # Sample grid: each output char represents a CHAR_RATIO vertical strip
    sample_w = width
    sample_h = int(height * CHAR_RATIO)

    resized = img.resize((sample_w, sample_h), Image.Resampling.LANCZOS)
    pixels = resized.load()

    step_v = sample_h / height  # how many sample rows per output row

    # ---- Build 2D luminance grid (height × width) ----
    lum_grid = [[0.0] * width for _ in range(height)]

    for r in range(height):
        sy0 = int(r * step_v)
        sy1 = int((r + 1) * step_v)
        if sy1 <= sy0:
            sy1 = sy0 + 1

        for c in range(width):
            total = 0.0
            count = 0
            for sy in range(sy0, sy1):
                r_, g_, b_, a_ = pixels[c, sy]
                alpha = a_ / 255.0
                # Rec. 601 luma
                lum = 0.299 * r_ + 0.587 * g_ + 0.114 * b_
                # Alpha compose onto white
                lum = lum * alpha + 255 * (1 - alpha)
                total += lum
                count += 1

            avg = total / count if count > 0 else 255.0

            # Contrast & brightness
            avg = (avg - 128) * contrast + 128 + brightness
            avg = max(0.0, min(255.0, avg))

            lum_grid[r][c] = avg

    # ---- Optional dithering ----
    if dither and ramp_len > 1:
        floyd_steinberg(lum_grid, ramp_len)

    # ---- Map to characters ----
    lines = []
    for r in range(height):
        row_chars = []
        for c in range(width):
            val = lum_grid[r][c]
            # Clamp to [0, 255]
            val = max(0.0, min(255.0, val))
            if invert:
                idx = ramp_len - 1 - int(val * (ramp_len - 1) / 255)
            else:
                idx = int(val * (ramp_len - 1) / 255)
            idx = max(0, min(ramp_len - 1, idx))
            row_chars.append(ramp[idx])
        lines.append("".join(row_chars))

    return ("\n".join(lines), width, height)


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="pixart — Pixel-density character art converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s photo.jpg\n"
            "  %(prog)s photo.jpg -w 120 -c blocks\n"
            "  %(prog)s photo.jpg -w 60 --dither --contrast 1.5\n"
        ),
    )
    parser.add_argument("image", help="Input image path")
    parser.add_argument("-w", "--width", type=int, default=80,
                        help="Output character width (default: 80)")
    parser.add_argument("--height", type=int, default=0,
                        help="Output char height (0 = auto)")
    parser.add_argument("-c", "--char-set", default="detailed",
                        choices=list(RAMPS.keys()),
                        help=f"Character ramp (default: detailed)")
    parser.add_argument("-i", "--invert", action="store_true",
                        help="Invert (dark background)")
    parser.add_argument("--contrast", type=float, default=1.0,
                        help="Contrast multiplier (default: 1.0)")
    parser.add_argument("--brightness", type=float, default=0,
                        help="Brightness offset -128..128 (default: 0)")
    parser.add_argument("-d", "--dither", action="store_true",
                        help="Enable Floyd-Steinberg dithering")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress stats on stderr")

    args = parser.parse_args()

    art, w, h = convert_image(
        args.image,
        width=args.width,
        height=args.height,
        char_set=args.char_set,
        invert=args.invert,
        contrast=args.contrast,
        brightness=args.brightness,
        dither=args.dither,
    )

    sys.stdout.write(art)
    sys.stdout.write("\n")

    if not args.quiet:
        lines = art.split("\n")
        chars = sum(len(ln) for ln in lines)
        parts = [f"Size: {w}×{h} chars, total {chars} chars, ramp: {args.char_set}"]
        if args.dither:
            parts.append("dither: on")
        print(", ".join(parts), file=sys.stderr)


if __name__ == "__main__":
    main()
