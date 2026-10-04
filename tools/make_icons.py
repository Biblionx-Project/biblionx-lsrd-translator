"""Generate the browser extension PNG icons (16/32/48/128) with the stdlib only.

Draws a rounded indigo square with a white "B" glyph, anti-aliased by 4x4
supersampling. Run from the repo root:  python tools/make_icons.py
"""
import os
import struct
import zlib

INDIGO = (79, 70, 229)
WHITE = (255, 255, 255)
SS = 4  # supersampling per axis


def inside_square(x, y, radius=0.22):
    """Rounded square covering the whole unit canvas (with a tiny margin)."""
    m = 0.02
    if x < m or x > 1 - m or y < m or y > 1 - m:
        return False
    cx = min(max(x, m + radius), 1 - m - radius)
    cy = min(max(y, m + radius), 1 - m - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def bowl(x, y, cy, ry, rx, stroke):
    """Right-hand half-ring of a "B" bowl centred at (0.43, cy)."""
    if x < 0.43:
        return False
    dx, dy = (x - 0.43), (y - cy)
    outer = (dx / rx) ** 2 + (dy / ry) ** 2 <= 1
    inner = (dx / (rx - stroke)) ** 2 + (dy / (ry - stroke)) ** 2 <= 1
    return outer and not inner


def inside_glyph(x, y):
    stroke = 0.095
    if 0.29 <= x <= 0.29 + stroke + 0.02 and 0.22 <= y <= 0.78:  # stem
        return True
    if 0.29 <= x <= 0.45 and (0.22 <= y <= 0.22 + stroke or 0.78 - stroke <= y <= 0.78
                              or 0.50 - stroke / 2 <= y <= 0.50 + stroke / 2):  # arms
        return True
    return bowl(x, y, 0.36, 0.14, 0.2, stroke) or bowl(x, y, 0.64, 0.14, 0.22, stroke)


def render(size):
    rows = []
    for py in range(size):
        row = bytearray([0])  # filter type 0
        for px in range(size):
            a = g = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) / size
                    y = (py + (sy + 0.5) / SS) / size
                    if inside_square(x, y):
                        a += 1
                        if inside_glyph(x, y):
                            g += 1
            n = SS * SS
            if a == 0:
                row += bytes((0, 0, 0, 0))
                continue
            t = g / a
            r = round(INDIGO[0] * (1 - t) + WHITE[0] * t)
            gr = round(INDIGO[1] * (1 - t) + WHITE[1] * t)
            b = round(INDIGO[2] * (1 - t) + WHITE[2] * t)
            row += bytes((r, gr, b, round(255 * a / n)))
        rows.append(bytes(row))
    return b"".join(rows)


def chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path, size):
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(render(size), 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "browser_extension", "icons")
    os.makedirs(out, exist_ok=True)
    for s in (16, 32, 48, 128):
        write_png(os.path.join(out, f"icon{s}.png"), s)
        print(f"wrote icon{s}.png")


if __name__ == "__main__":
    main()
