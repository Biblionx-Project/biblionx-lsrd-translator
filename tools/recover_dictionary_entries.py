# /// script
# requires-python = ">=3.10"
# dependencies = ["pdfminer.six", "pypdfium2", "pillow"]
# ///
"""Recover entries of the official LSRD dictionary PDF that are missing from the database.

Usage (from the repository root):

    uv run tools/recover_dictionary_entries.py --pdf <dictionary.pdf> \
        --db lsrd_dictionary.db --images extracted_images [--apply] [--pages 190-200]

Without --apply the script only parses the PDF and prints the diff (read-only).
With --apply it backs up the database (--backup), inserts every verified missing entry
(new ids continue after the current maximum, existing rows and ids are never touched) and
crops each entry's illustration to <images>/lsrd_XXXX.png. Re-running inserts nothing new.

How the PDF is read
-------------------
Every PDF page is a two-page spread. Each half has a grid of up to three cells separated by
thin horizontal rules; a cell holds one entry, or a small group of entries that share one
illustration and one movement description (e.g. GRAPA / GRAPADORA / GRAPAR). Inside a cell
the text column is typeset with fixed styles, which is what the parser keys on:

    headword        Poppins-ExtraBold, ~18 pt, uppercase (may wrap to a second line)
    category        Poppins-Light, 6 pt        ("Sustantivo masculino.", "Verbo transitivo.")
    definition      Poppins-SemiBold, 10 pt
    movement text   Poppins-Regular, 9 pt      (sometimes numbered steps)

The illustration fills the rest of the cell on the other side of the text column.

Dependencies: pdfminer.six (pure Python) gives text lines with font names, sizes and
coordinates; pypdfium2 renders the illustration crops. PyMuPDF would do both, but its
native library is blocked by Windows Application Control on the development machine.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field

RENDER_SCALE = 2.0     # 144 dpi, the resolution of the existing crops (~540 px wide)
TOP_LIMIT_MARGIN = 25  # points below the top edge (coloured header bar)
BOTTOM_LIMIT = 89      # points above the bottom edge (page numbers sit at y=77..87)


# ----------------------------------------------------------------- normalisation
def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def palabra_norm(palabra_es):
    """Same rule as the existing rows: lowercase, accents removed, punctuation kept."""
    return strip_accents(palabra_es.lower()).strip()


def key(text):
    """Comparison key: lowercase, no accents, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", strip_accents(text.lower()))


def clean(text):
    text = re.sub(r"-\s+(?=[a-záéíóúñ])", "", text)  # re-join hyphenated line breaks
    return re.sub(r"\s+", " ", text).strip()


# ----------------------------------------------------------------- PDF layout
@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    font: str

    @property
    def kind(self):
        f = self.font
        if "Poppins" not in f:
            return "other"               # step numbers (MyriadPro) and similar
        if "ExtraBold" in f and 14 <= self.size <= 20 and re.search(r"[A-ZÁÉÍÓÚÑ]", self.text):
            return "headword"
        if "Light" in f and self.size < 8:
            return "category"
        if "SemiBold" in f:
            return "definition"
        if "Regular" in f:
            return "body"
        return "other"                   # page numbers (Poppins-Medium), etc.


@dataclass
class Entry:
    page: int
    headword: str
    category: str = ""
    definition: str = ""
    description: str = ""
    shared_description: bool = False
    group: list = field(default_factory=list)
    illustration: tuple = None           # (x0, y0, x1, y1) in PDF points
    head_lines: list = field(default_factory=list)

    @property
    def clean_parse(self):
        return bool(self.headword and self.category and self.definition
                    and self.description and self.illustration)


def read_layout(pdf_path, pages=None):
    """Yield (page_number, width, height, lines, rules) for each page (1-based numbers)."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTCurve, LTLine, LTRect, LTTextLine

    numbers = None if pages is None else [p - 1 for p in pages]
    for idx, layout in enumerate(extract_pages(pdf_path, page_numbers=numbers, laparams=LAParams())):
        pno = pages[idx] if pages is not None else idx + 1
        lines, rules = [], []

        def walk(obj):
            if isinstance(obj, LTTextLine):
                chars = [c for c in obj if isinstance(c, LTChar)]
                text = obj.get_text().strip()
                if chars and text:
                    lines.append(Line(text, *obj.bbox, size=max(c.size for c in chars),
                                      font=chars[0].fontname.split("+")[-1]))
                return
            if isinstance(obj, (LTLine, LTRect, LTCurve)) and obj.width > 150 and obj.height < 3:
                rules.append(obj.bbox)
                return
            if hasattr(obj, "__iter__"):
                for child in obj:
                    walk(child)

        walk(layout)
        yield pno, layout.width, layout.height, lines, rules


def continues(previous, nxt):
    """True when an ExtraBold line is the continuation of the headword printed above it.

    Two short headwords can also be stacked without anything in between (AGENDA / AGENDAR),
    so only wrap-like shapes are joined: an open parenthesis, a trailing comma, hyphen or
    connector word, or a continuation that starts with '('.
    """
    if previous.count("(") > previous.count(")") or nxt.startswith("("):
        return True
    if re.search(r"[,\-]$", previous):
        return True
    return bool(re.search(r"\b(DE|DEL|LA|LAS|LOS|EL|CON|Y|EN)$", previous))


def merge_headwords(heads):
    """Join a headword that wraps onto a second ExtraBold line ('BATERÍA (INSTRUMENTO' + 'MUSICAL)')."""
    heads = sorted(heads, key=lambda l: -l.y1)
    merged = []
    for line in heads:
        prev = merged[-1] if merged else None
        if (prev and prev[-1].y0 - line.y1 < 6 and abs(prev[-1].x0 - line.x0) < 4
                and continues(" ".join(l.text for l in prev), line.text)):
            prev.append(line)
        else:
            merged.append([line])
    return merged


def parse_page(pno, width, height, lines, rules):
    """Return the entries printed on one PDF page, in reading order."""
    entries = []
    halves = [(0, width / 2), (width / 2, width)] if width > 900 else [(0, width)]
    for hx0, hx1 in halves:
        in_half = [l for l in lines if hx0 <= (l.x0 + l.x1) / 2 < hx1]
        half_rules = [r for r in rules if hx0 <= (r[0] + r[2]) / 2 < hx1]
        if half_rules:
            cell_x0 = min(r[0] for r in half_rules) - 6
            cell_x1 = max(r[2] for r in half_rules) + 6
        else:
            cell_x0, cell_x1 = hx0 + (96 if hx0 == 0 else 85), hx1 - (85 if hx0 == 0 else 80)
        cuts = sorted({round(r[1], 1) for r in half_rules}, reverse=True)
        edges = [height - TOP_LIMIT_MARGIN] + cuts + [BOTTOM_LIMIT]
        bands = [(edges[i + 1], edges[i]) for i in range(len(edges) - 1)]

        for b0, b1 in bands:
            cell = [l for l in in_half if b0 <= (l.y0 + l.y1) / 2 < b1]
            heads = merge_headwords([l for l in cell if l.kind == "headword"])
            if not heads:
                continue
            column = [l for l in cell if l.kind in ("headword", "category", "definition", "body")]
            tx0 = min(l.x0 for l in column)
            tx1 = max(l.x1 for l in column)
            # Illustration: the wider free side of the cell, next to the text column.
            if tx0 - cell_x0 >= cell_x1 - tx1:
                ill = (cell_x0, b0 + 3, tx0 - 3, b1 - 3)
            else:
                ill = (tx1 + 3, b0 + 3, cell_x1, b1 - 3)

            group = []
            for i, head in enumerate(heads):
                top = head[0].y1 + 1
                bottom = heads[i + 1][0].y1 + 1 if i + 1 < len(heads) else b0
                own = [l for l in column if bottom <= (l.y0 + l.y1) / 2 <= top and l not in head]
                own.sort(key=lambda l: (-round(l.y1), l.x0))
                e = Entry(page=pno,
                          headword=clean(" ".join(l.text for l in head)),
                          category=clean(" ".join(l.text for l in own if l.kind == "category")),
                          definition=clean(" ".join(l.text for l in own if l.kind == "definition")),
                          description=clean(" ".join(l.text for l in own if l.kind == "body")),
                          illustration=ill,
                          head_lines=[l.text for l in head])
                group.append(e)
            # Grouped entries print one movement description (after the last headword).
            shared = next((e.description for e in reversed(group) if e.description), "")
            for e in group:
                e.group = [g.headword for g in group]
                if not e.description and shared:
                    e.description, e.shared_description = shared, True
            entries.extend(group)
    return entries


# ----------------------------------------------------------------- database diff
def load_db(conn):
    rows = conn.execute("SELECT id, palabra_es, palabra_norm, pagina FROM palabras").fetchall()
    keys = {}
    page_keys = {}
    for pid, es, norm, page in rows:
        for k in (key(es), key(norm)):
            keys.setdefault(k, (pid, es, page))
            page_keys.setdefault(page, set()).add(k)
    return keys, page_keys


def split_in_db(entry, page_keys):
    """True when the DB already holds this headword split in pieces.

    The original extraction stored some wrapped or parenthesised headwords as one row per
    printed line or piece ('PERAVIA' + '(BANÍ)', 'BATERÍA' + '(INSTRUMENTO'). Those rows are
    left as they are; the entry is not inserted again.
    """
    keys_here = page_keys.get(entry.page, set())

    def pieces(lines):
        return [p for line in lines for p in re.split(r"\s+(?=\()", line) if key(p)]

    lines = [l for l in entry.head_lines if key(l)]
    for candidate in (lines, pieces(entry.head_lines), pieces(entry.head_lines[:1])):
        if len(candidate) > 1 and all(key(p) in keys_here for p in candidate):
            return True
    return False


def diff(entries, conn):
    keys, page_keys = load_db(conn)
    missing, split, elsewhere = [], [], []
    for e in entries:
        k = key(e.headword)
        if k in keys:
            if keys[k][2] != e.page:
                elsewhere.append((e, keys[k]))
            continue
        if split_in_db(e, page_keys):
            split.append(e)
            continue
        missing.append(e)
    return missing, split, elsewhere


# ----------------------------------------------------------------- insertion
def category_id(conn, name, created):
    if not name:
        return None
    row = conn.execute("SELECT id FROM categorias WHERE nombre = ?", (name,)).fetchone()
    if row:
        return row[0]
    wanted = key(name)
    for cid, nombre in conn.execute("SELECT id, nombre FROM categorias ORDER BY id"):
        if key(nombre) == wanted:
            return cid
    cur = conn.execute("INSERT INTO categorias (nombre) VALUES (?)", (name,))
    created.append(name)
    return cur.lastrowid


def next_id_number(conn):
    best = 0
    for (pid,) in conn.execute("SELECT id FROM palabras"):
        m = re.fullmatch(r"lsrd_(\d+)", pid or "")
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def render_crops(pdf_path, jobs, images_dir):
    """jobs: list of (page, rect, [file names]). Renders each rect once, trims white margins."""
    import pypdfium2 as pdfium
    from PIL import ImageChops, Image

    os.makedirs(images_dir, exist_ok=True)
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for page_no, rect, names in jobs:
            page = pdf[page_no - 1]
            width, height = page.get_size()
            x0, y0, x1, y1 = rect
            crop = (max(0, x0), max(0, y0), max(0, width - x1), max(0, height - y1))
            img = page.render(scale=RENDER_SCALE, crop=crop).to_pil().convert("RGB")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            diff_img = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 18 else 0)
            box = diff_img.getbbox()
            if box:
                pad = 12
                img = img.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                                min(img.width, box[2] + pad), min(img.height, box[3] + pad)))
            for name in names:
                img.save(os.path.join(images_dir, name), optimize=True)
    finally:
        pdf.close()


def apply(conn, missing, pdf_path, images_dir, backup_path, db_path):
    if backup_path:
        os.makedirs(os.path.dirname(os.path.abspath(backup_path)), exist_ok=True)
        shutil.copy2(db_path, backup_path)
    created, inserted, jobs = [], [], {}
    n = next_id_number(conn)
    with conn:
        for e in missing:
            pid = f"lsrd_{n:04d}"
            n += 1
            review = 0 if e.clean_parse else 1
            conn.execute(
                "INSERT INTO palabras (id, palabra_es, palabra_norm, categoria_id, definicion_es,"
                " pagina, requiere_revision) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, e.headword, palabra_norm(e.headword), category_id(conn, e.category, created),
                 e.definition or None, e.page, review))
            if e.description:
                conn.execute("INSERT INTO senas_descripciones (palabra_id, descripcion_sena) VALUES (?, ?)",
                             (pid, e.description))
            path = f"extracted_images/{pid}.png"
            conn.execute("INSERT INTO rutas_imagenes (palabra_id, ruta_imagen, es_principal) VALUES (?, ?, 1)",
                         (pid, path))
            if e.illustration:
                jobs.setdefault((e.page, e.illustration), []).append(f"{pid}.png")
            inserted.append((pid, e))
    if images_dir and jobs:
        render_crops(pdf_path, [(p, r, names) for (p, r), names in jobs.items()], images_dir)
    return inserted, created


# ----------------------------------------------------------------- CLI
def parse_pages(spec):
    if not spec:
        return None
    pages = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pdf", required=True, help="official dictionary PDF")
    ap.add_argument("--db", default="lsrd_dictionary.db")
    ap.add_argument("--images", default="extracted_images", help="directory for the crops")
    ap.add_argument("--apply", action="store_true", help="insert the missing entries")
    ap.add_argument("--backup", help="copy the DB here before --apply (default: <db>.bak)")
    ap.add_argument("--pages", help="only parse these PDF pages, e.g. '113' or '190-200,414'")
    ap.add_argument("--first-page", type=int, default=29, help="first page with entries")
    ap.add_argument("--report", help="write the diff as JSON here")
    args = ap.parse_args(argv)

    pages = parse_pages(args.pages)
    entries = []
    for pno, width, height, lines, rules in read_layout(args.pdf, pages):
        if pno >= args.first_page:
            entries.extend(parse_page(pno, width, height, lines, rules))

    conn = sqlite3.connect(args.db)
    try:
        missing, split, elsewhere = diff(entries, conn)
        print(f"parsed {len(entries)} entries; missing from DB: {len(missing)}; "
              f"split across rows in DB (left unchanged): {len(split)}; "
              f"same headword on another page: {len(elsewhere)}")
        for e in missing:
            flag = "ok" if e.clean_parse else "REVIEW"
            shared = " (shared description)" if e.shared_description else ""
            print(f"  MISSING p.{e.page:<3} {e.headword:<22} [{e.category}] {flag}{shared}")
        for e in split:
            print(f"  SPLIT   p.{e.page:<3} {e.headword}")
        report = {"parsed": len(entries),
                  "missing": [e.__dict__ for e in missing],
                  "split_in_db": [e.headword for e in split],
                  "other_page": [(e.headword, e.page, row[0], row[2]) for e, row in elsewhere]}
        if args.apply and missing:
            backup = args.backup or args.db + ".bak"
            inserted, created = apply(conn, missing, args.pdf, args.images, backup, args.db)
            print(f"inserted {len(inserted)} entries (backup: {backup})")
            for pid, e in inserted:
                print(f"  {pid}  p.{e.page}  {e.headword}")
            if created:
                print(f"new categorias rows: {created}")
            report["inserted"] = [(pid, e.headword, e.page) for pid, e in inserted]
        elif args.apply:
            print("nothing to insert (already up to date)")
        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=1)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
