# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfminer.six", "pypdfium2"]
# ///
"""Regenerate sign illustrations (extracted_images/lsrd_XXXX.png) from the official LSRD PDF.

Usage (from the repository root):

    uv run tools/recrop_sign_images.py --pdf <dictionary.pdf> --backup <dir> --bad-from bad.json
    uv run tools/recrop_sign_images.py --pdf <dictionary.pdf> --backup <dir> --ids lsrd_0001
    uv run tools/recrop_sign_images.py --pdf <dictionary.pdf> --all --dry-run out_dir/
    uv run tools/recrop_sign_images.py --qa-only            # only score the current images

Why: the original extraction cropped a fixed region per entry and, for about half of the
entries, that region held dictionary text (headword, definition) instead of the drawing.
This tool locates each entry's headword on its page (palabras.pagina), takes the
illustration of the same grid cell (the free side of the cell next to the text column,
see tools/recover_dictionary_entries.py for the page model), renders it with pypdfium2 at
144 dpi (scale 2, the resolution of the existing crops), trims the white margin and writes
<images>/<id>.png. Database rows, ids and image paths are never modified.

QA: every written image is scored with a skin-tone pixel rule (every illustration shows a
person signing, drawn with flat skin-tone hands and face). A crop that scores below
SKIN_THRESHOLD almost certainly shows text or blank paper and is reported.

Before overwriting anything the current image folder is copied to --backup (required; an
existing backup is never overwritten). --dry-run writes to a separate folder instead.

Dependencies: pdfminer.six (layout) and pypdfium2 (rendering); PNG encode/decode is
stdlib (zlib), so Pillow is not needed.
"""
import argparse
import json
import os
import shutil
import sqlite3
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recover_dictionary_entries import key, parse_page, read_layout  # noqa: E402

RENDER_SCALE = 2.0      # 144 dpi, same as the existing crops
WHITE_LEVEL = 237       # a pixel channel below this counts as ink when trimming margins
TRIM_PAD = 12           # pixels kept around the trimmed drawing
OUTER_BLEED = 12        # points added on the page-edge side of the illustration rect
EDGE_GAP = 20           # white columns that separate page furniture from the drawing
EDGE_BLOCK = 130        # max width (px) of an edge block that may be dropped as furniture
SKIN_THRESHOLD = 0.005  # good crops score ~0.05-0.2, text-only crops score 0.0
SAMPLE_STEP = 3         # score every 3rd pixel of every 3rd row


# ----------------------------------------------------------------- PNG (stdlib)
def png_encode(width, height, rgb_rows):
    """rgb_rows: list of bytes objects (width*3 each). Returns PNG bytes (filter 0)."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + row for row in rgb_rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def png_decode(path):
    """Decode an 8-bit, non-interlaced PNG. Returns (width, height, bpp, pixels) or None."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    i, idat, palette = 8, [], None
    width = height = depth = ctype = interlace = None
    while i < len(data):
        (n,) = struct.unpack(">I", data[i:i + 4])
        tag, body = data[i + 4:i + 8], data[i + 8:i + 8 + n]
        i += 12 + n
        if tag == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            palette = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    if depth != 8 or interlace:
        return None
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if bpp is None:
        return None
    raw = zlib.decompress(b"".join(idat))
    stride = width * bpp
    out = bytearray(stride * height)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif f == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif f == 3:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if ctype == 3 and palette:            # expand palette to RGB
        rgb = bytearray()
        for v in out:
            rgb += palette[3 * v:3 * v + 3]
        return width, height, 3, rgb
    return width, height, bpp, out


def is_skin(r, g, b):
    return (r > 170 and g > 120 and b > 80 and r - b > 35 and r > g > b and r - g < 70)


def skin_score(path):
    """Fraction of sampled pixels with an illustration skin tone (None if undecodable)."""
    decoded = png_decode(path)
    if not decoded:
        return None
    width, height, bpp, px = decoded
    if bpp < 3:
        return 0.0
    hits = total = 0
    for y in range(0, height, SAMPLE_STEP):
        row = y * width * bpp
        for x in range(0, width, SAMPLE_STEP):
            o = row + x * bpp
            total += 1
            if is_skin(px[o], px[o + 1], px[o + 2]):
                hits += 1
    return hits / max(total, 1)


# ----------------------------------------------------------------- rendering
_INK = bytes(1 if v < WHITE_LEVEL else 0 for v in range(256))


def render_rect(pdf, page_no, rect):
    """Render a PDF rect (points, origin bottom-left) to (width, height, [rgb rows]), trimmed."""
    page = pdf[page_no - 1]
    pw, ph = page.get_size()
    x0, y0, x1, y1 = rect
    crop = (max(0, x0), max(0, y0), max(0, pw - x1), max(0, ph - y1))
    bitmap = page.render(scale=RENDER_SCALE, crop=crop, rev_byteorder=True,
                         fill_color=(255, 255, 255, 255))
    width, height, stride = bitmap.width, bitmap.height, bitmap.stride
    nch = stride // width if width else 3
    buf = bytes(bitmap.buffer)
    rows = []
    for y in range(height):
        line = buf[y * stride:y * stride + width * nch]
        if nch == 4:                              # drop the padding/alpha byte
            rgb = bytearray(width * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = line[0::4], line[1::4], line[2::4]
            line = bytes(rgb)
        rows.append(line)
    return trim(width, height, rows)


def _has_skin(rows, x0, x1):
    for line in rows[::2]:
        for x in range(x0, x1, 2):
            if is_skin(line[3 * x], line[3 * x + 1], line[3 * x + 2]):
                return True
    return False


def trim(width, height, rows):
    """Trim white margins and page furniture around the drawing.

    - Rows that are one flat colour across most of the width are grid rules or the coloured
      header bar: they are painted white.
    - Ink columns are split into blocks separated by EDGE_GAP white columns. A narrow block
      at the left/right edge without any skin tone is page furniture (the vertical running
      title "DICCIONARIO OFICIAL DE LA LENGUA..." and the logo) and is dropped.
    - The rest is cropped to the ink bounding box plus TRIM_PAD pixels.
    """
    white = b"\xff" * (width * 3)
    acc = 0
    for y, line in enumerate(rows):
        ink = line.translate(_INK)
        first = ink.find(1)
        if first < 0:
            continue
        last = ink.rfind(1)
        span = line[first - first % 3:last - last % 3 + 3]
        if (last - first) // 3 > 0.5 * width and len(set(span)) <= 8:
            rows[y] = white
            continue
        acc |= int.from_bytes(ink, "big")
    if not acc:
        return width, height, rows
    colmask = acc.to_bytes(width * 3, "big")
    cols = [colmask[3 * x] | colmask[3 * x + 1] | colmask[3 * x + 2] for x in range(width)]
    blocks, start, gap = [], None, 0
    for x, c in enumerate(cols):
        if c:
            if start is None:
                start = x
            elif gap >= EDGE_GAP:
                blocks.append([start, x - gap])
                start = x
            gap = 0
        elif start is not None:
            gap += 1
    blocks.append([start, width - gap])
    while len(blocks) > 1:
        a, b = blocks[0]
        if b - a < EDGE_BLOCK and not _has_skin(rows, a, b):
            blocks.pop(0)
            continue
        a, b = blocks[-1]
        if b - a < EDGE_BLOCK and not _has_skin(rows, a, b):
            blocks.pop()
            continue
        break
    left, right = blocks[0][0], blocks[-1][1]
    top = bottom = None
    for y, line in enumerate(rows):
        if line[3 * left:3 * right].translate(_INK).find(1) >= 0:
            top = y if top is None else top
            bottom = y
    l = max(0, left - TRIM_PAD)
    r = min(width, right + TRIM_PAD)
    t = max(0, top - TRIM_PAD)
    b = min(height, bottom + 1 + TRIM_PAD)
    return r - l, b - t, [row[3 * l:3 * r] for row in rows[t:b]]


def outer_rect(pdf, page_no, rect):
    """Widen the illustration rect by OUTER_BLEED points towards the page edge.

    The cell edge is derived from the grid rules, but arms and step numbers often reach a
    few points past the rule ends. The running title further out is removed by trim().
    """
    pw = pdf[page_no - 1].get_size()[0]
    x0, y0, x1, y1 = rect
    half = (0, pw / 2) if pw > 900 and (x0 + x1) / 2 < pw / 2 else         ((pw / 2, pw) if pw > 900 else (0, pw))
    if (x0 + x1) / 2 < (half[0] + half[1]) / 2:
        return (x0 - OUTER_BLEED, y0, x1, y1)
    return (x0, y0, x1 + OUTER_BLEED, y1)


# ----------------------------------------------------------------- matching
def db_rows(conn):
    """{id: (palabra_es, pagina, image_path)} for every entry that has an lsrd_*.png image."""
    out = {}
    for pid, es, page, path in conn.execute(
            "SELECT p.id, p.palabra_es, p.pagina, r.ruta_imagen FROM palabras p "
            "JOIN rutas_imagenes r ON r.palabra_id = p.id ORDER BY p.id"):
        out[pid] = (es, page, path)
    return out


def candidates(word):
    """Comparison keys for a DB headword: full form and its comma/parenthesis pieces."""
    full = key(word)
    keys = [full] if full else []
    for sep in (",", "("):
        first = key(word.split(sep)[0])
        if first and first not in keys:
            keys.append(first)
    return keys


def match_entry(word, entries, windows=()):
    """Pick the parsed entry whose headword matches the DB headword. Returns (entry, how).

    windows: joined keys of this row with its DB neighbours on the same page. The original
    extraction stored some wrapped headwords as one row per printed piece ('BATERÍA',
    '(INSTRUMENTO', 'MUSICAL)'); joining the pieces back identifies the entry exactly.
    """
    wanted = candidates(word)
    if not wanted:
        return None, None
    by_key = {}
    for e in entries:
        by_key.setdefault(key(e.headword), e)
    if wanted[0] in by_key:
        return by_key[wanted[0]], "exact"
    for joined in windows:
        if joined in by_key:
            return by_key[joined], "joined"
    # DB row holds one printed line / piece of a wrapped headword ('PERAVIA' + '(BANÍ)').
    for e in entries:
        lines = [key(p) for l in e.head_lines for p in l.replace("(", ",(").split(",")]
        pieces = [key(p) for p in e.headword.replace("(", ",(").split(",")]
        if any(p == wanted[0] or (len(wanted[0]) >= 4 and p.startswith(wanted[0]))
               for p in lines + pieces):
            return e, "piece"
    for w in wanted[1:]:
        if w in by_key:
            return by_key[w], "first-part"
    # prefix either way (truncated headwords, OCR-ish differences in the old extraction)
    full = wanted[0]
    best = None
    for k, e in by_key.items():
        if len(full) >= 3 and len(k) >= 3 and (k.startswith(full) or full.startswith(k)):
            score = min(len(k), len(full))
            if best is None or score > best[0]:
                best = (score, e)
    if best:
        return best[1], "prefix"
    return None, None


class PageCache:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.cache = {}

    def load(self, pages):
        todo = sorted({p for p in pages if p not in self.cache and p >= 1})
        if not todo:
            return
        for pno, width, height, lines, rules in read_layout(self.pdf_path, todo):
            self.cache[pno] = parse_page(pno, width, height, lines, rules)

    def entries(self, page):
        self.load([page])
        return self.cache.get(page, [])


def neighbour_windows(pid, page_rows):
    """Joined keys of 2-3 consecutive DB rows (same page, id order) that include pid."""
    ids = [i for i, _ in page_rows]
    if pid not in ids:
        return []
    i = ids.index(pid)
    out = []
    for size in (2, 3):
        for start in range(i - size + 1, i + 1):
            if start >= 0 and start + size <= len(ids):
                out.append(key("".join(w for _, w in page_rows[start:start + size])))
    return out


def locate(word, page, pages, windows=()):
    """Find (entry, page, how) for a DB headword, trying its page then the neighbours."""
    for p, tag in ((page, ""), (page - 1, "@-1"), (page + 1, "@+1")):
        e, how = match_entry(word, pages.entries(p), windows if p == page else ())
        if e:
            return e, p, how + tag
    return None, None, None


# ----------------------------------------------------------------- CLI
def score_all(images_dir, ids, rows):
    low = []
    for pid in ids:
        path = os.path.join(images_dir, os.path.basename(rows[pid][2]))
        s = skin_score(path) if os.path.exists(path) else None
        if s is None or s < SKIN_THRESHOLD:
            low.append((pid, s))
    return low


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pdf", help="official dictionary PDF")
    ap.add_argument("--db", default="lsrd_dictionary.db")
    ap.add_argument("--images", default="extracted_images", help="image folder to update")
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--ids", nargs="+", help="entry ids (lsrd_0001 ...)")
    sel.add_argument("--all", action="store_true", help="every DB entry with an image")
    sel.add_argument("--bad-from", help="JSON file with a 'bad_ids' list (or a plain list)")
    ap.add_argument("--dry-run", metavar="DIR", help="write the crops to DIR instead of --images")
    ap.add_argument("--backup", help="copy --images here before overwriting (required unless "
                                     "--dry-run or --no-backup; keep it outside the repository; "
                                     "an existing backup is never overwritten)")
    ap.add_argument("--no-backup", action="store_true", help="overwrite without a backup")
    ap.add_argument("--qa-only", action="store_true", help="only score the current images")
    ap.add_argument("--report", help="write a JSON report here")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    rows = db_rows(conn)
    by_page = {}
    for pid, word, page in conn.execute("SELECT id, palabra_es, pagina FROM palabras ORDER BY id"):
        by_page.setdefault(page, []).append((pid, word))
    conn.close()

    if args.ids:
        ids = args.ids
    elif args.bad_from:
        with open(args.bad_from, encoding="utf-8") as fh:
            data = json.load(fh)
        ids = data["bad_ids"] if isinstance(data, dict) else data
    else:
        ids = sorted(rows)
    unknown = [i for i in ids if i not in rows]
    ids = [i for i in ids if i in rows]
    if unknown:
        print(f"ignored {len(unknown)} ids without an image row: {unknown[:10]}")

    if args.qa_only:
        low = score_all(args.images, ids, rows)
        print(f"QA: {len(ids) - len(low)}/{len(ids)} images pass (skin >= {SKIN_THRESHOLD})")
        for pid, s in low:
            print(f"  LOW {pid} {rows[pid][0]!r} p.{rows[pid][1]} score={s}")
        return 1 if low else 0

    if not args.pdf:
        ap.error("--pdf is required unless --qa-only")
    out_dir = args.dry_run or args.images
    if not args.dry_run and not args.backup and not args.no_backup:
        ap.error("--backup DIR is required when overwriting images (or pass --no-backup)")
    if not args.dry_run and args.backup and os.path.isdir(args.images):
        backup = args.backup
        if os.path.exists(backup):
            print(f"backup exists, not overwritten: {backup}")
        else:
            shutil.copytree(args.images, backup)
            print(f"backed up {args.images} -> {backup}")
    os.makedirs(out_dir, exist_ok=True)

    import pypdfium2 as pdfium
    pages = PageCache(args.pdf)
    pages.load({rows[pid][1] for pid in ids})

    pdf = pdfium.PdfDocument(args.pdf)
    written, unmatched, low, report = [], [], [], {}
    try:
        for n, pid in enumerate(ids, 1):
            word, page, path = rows[pid]
            entry, at, how = locate(word, page, pages,
                                    neighbour_windows(pid, by_page.get(page, [])))
            if not entry:
                unmatched.append(pid)
                report[pid] = {"word": word, "page": page, "status": "unmatched"}
                print(f"  UNMATCHED {pid} {word!r} p.{page}")
                continue
            w, h, img_rows = render_rect(pdf, at, outer_rect(pdf, at, entry.illustration))
            target = os.path.join(out_dir, os.path.basename(path))
            with open(target, "wb") as fh:
                fh.write(png_encode(w, h, img_rows))
            s = skin_score(target)
            written.append(pid)
            report[pid] = {"word": word, "page": page, "matched": entry.headword,
                           "match_page": at, "how": how, "size": [w, h], "skin": round(s, 4)}
            if s < SKIN_THRESHOLD:
                low.append(pid)
                print(f"  LOW-SKIN {pid} {word!r} -> {entry.headword!r} p.{at} score={s:.4f}")
            if n % 100 == 0:
                print(f"  ... {n}/{len(ids)}")
    finally:
        pdf.close()

    print(f"written {len(written)} to {out_dir}; unmatched {len(unmatched)}; "
          f"low skin score {len(low)} (threshold {SKIN_THRESHOLD})")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    return 0 if not (unmatched or low) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
