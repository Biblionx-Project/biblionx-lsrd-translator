"""Apply the reviewed dictionary fixes in data/dictionary_fixes.json to lsrd_dictionary.db.

Usage (from the repository root):

    python tools/apply_dictionary_fixes.py --dry-run     # report only, nothing is written
    python tools/apply_dictionary_fixes.py               # apply in one transaction

The fixes file is built from a page-by-page audit of the official dictionary PDF; every op
carries the PDF evidence it is based on. Op types:

    update          set one field of one row: palabra_es (palabra_norm follows), categoria
                    (by name; an existing categorias row is reused), definicion_es or
                    descripcion_sena. 'old' must match the database, unless the row
                    already holds 'new' (then the op is skipped).
    insert          a printed entry missing from the database; it gets the next free id
                    after the current maximum (recorded in id_map).
    merge_split     one printed headword stored as several rows. The kept row gets the full
                    headword, any field it lacks from the fragments, and every reference of
                    the fragments (sinonimos_mapeo, data/synonyms_extra.json); then the
                    fragment rows and their descriptions/image rows are deleted.
    delete_divider  a row made from a letter-divider page (no entry printed). References
                    move to the letter's own sign, then the row is deleted.
    add_synonym     a name printed inside a merged headword, added to sinonimos_mapeo.
    flag            the PDF itself lacks a field; the row keeps requiere_revision=1.

After the ops, requiere_revision is recomputed for every row: 0 when the row has a
category, a definition and a movement description and is not flagged, otherwise 1.
Category rows no longer referenced by any entry are removed.

Idempotent: a second run finds every op already applied and changes nothing. Any conflict
(an 'old' value that matches neither the database nor 'new') aborts the whole run and
rolls the transaction back. Fingerspelling letter ids are never merged away or deleted.
Standard library only.
"""
import argparse
import json
import os
import sqlite3
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIN_CATEGORIA = "Sin Categoría"
FIELDS = ("palabra_es", "categoria", "definicion_es", "descripcion_sena")

# Ids the fingerspelling alphabet uses (translator.DACTYL_LETTER_MAP); they never change.
LETTER_IDS = frozenset(
    "lsrd_%04d" % n for n in (1, 262, 372, 678, 807, 971, 1040, 1090, 1155, 1222, 1242, 1248,
                              1327, 1475, 1526, 1527, 1582, 1799, 1815, 1907, 2028, 2157,
                              2170, 2237, 2239, 2240, 2247))


class Conflict(Exception):
    pass


def palabra_norm(palabra_es):
    """Same rule as the existing rows: lowercase, accents removed, punctuation kept."""
    return "".join(c for c in unicodedata.normalize("NFD", palabra_es.lower())
                   if unicodedata.category(c) != "Mn").strip()


def image_path(pid):
    return "extracted_images/%s.png" % pid


# ----------------------------------------------------------------- field access
def get_field(con, pid, field):
    if field == "categoria":
        row = con.execute("SELECT c.nombre FROM palabras p LEFT JOIN categorias c "
                          "ON c.id = p.categoria_id WHERE p.id = ?", (pid,)).fetchone()
        return row[0] if row else None
    if field == "descripcion_sena":
        row = con.execute("SELECT descripcion_sena FROM senas_descripciones WHERE palabra_id = ? "
                          "ORDER BY id", (pid,)).fetchone()
        return row[0] if row else ""
    row = con.execute("SELECT %s FROM palabras WHERE id = ?" % field, (pid,)).fetchone()
    return row[0] if row else None


def category_id(con, name, stats):
    row = con.execute("SELECT id FROM categorias WHERE nombre = ?", (name,)).fetchone()
    if row:
        return row[0]
    stats["categories_created"] += 1
    return con.execute("INSERT INTO categorias (nombre) VALUES (?)", (name,)).lastrowid


def set_field(con, pid, field, value, stats):
    if field == "categoria":
        con.execute("UPDATE palabras SET categoria_id = ? WHERE id = ?",
                    (category_id(con, value, stats), pid))
    elif field == "descripcion_sena":
        rows = con.execute("SELECT id FROM senas_descripciones WHERE palabra_id = ? ORDER BY id",
                           (pid,)).fetchall()
        if not value:
            con.execute("DELETE FROM senas_descripciones WHERE palabra_id = ?", (pid,))
        elif rows:
            con.execute("UPDATE senas_descripciones SET descripcion_sena = ? WHERE id = ?",
                        (value, rows[0][0]))
            con.execute("DELETE FROM senas_descripciones WHERE palabra_id = ? AND id <> ?",
                        (pid, rows[0][0]))
        else:
            con.execute("INSERT INTO senas_descripciones (palabra_id, descripcion_sena) VALUES (?, ?)",
                        (pid, value))
    elif field == "palabra_es":
        con.execute("UPDATE palabras SET palabra_es = ?, palabra_norm = ? WHERE id = ?",
                    (value, palabra_norm(value), pid))
    elif field == "definicion_es":
        con.execute("UPDATE palabras SET definicion_es = ? WHERE id = ?", (value, pid))
    else:
        raise ValueError("unknown field %r" % field)


def exists(con, pid):
    return con.execute("SELECT 1 FROM palabras WHERE id = ?", (pid,)).fetchone() is not None


def is_empty(field, value):
    if field == "categoria":
        return value in (None, "", SIN_CATEGORIA)
    return not (value or "").strip()


# ----------------------------------------------------------------- op handlers
def apply_update(con, op, stats):
    pid, field = op["id"], op["field"]
    if field not in FIELDS:
        raise Conflict("%s: unknown field %r" % (pid, field))
    if not exists(con, pid):
        raise Conflict("%s: row does not exist" % pid)
    if field == "palabra_es" and pid in LETTER_IDS:
        raise Conflict("%s: fingerspelling letter headwords are fixed" % pid)
    current = get_field(con, pid, field)
    if (current or "") == (op["new"] or ""):
        if field == "palabra_es" and get_field(con, pid, "palabra_norm") != palabra_norm(op["new"]):
            set_field(con, pid, field, op["new"], stats)
            return "applied"
        return "skipped"
    if (current or "") != (op.get("old") or ""):
        raise Conflict("%s.%s is %r, expected %r" % (pid, field, current, op.get("old")))
    set_field(con, pid, field, op["new"], stats)
    return "applied"


def next_id(con):
    nums = [int(r[0][5:]) for r in con.execute("SELECT id FROM palabras WHERE id LIKE 'lsrd_%'")]
    return "lsrd_%04d" % (max(nums) + 1)


def apply_insert(con, op, stats, id_map):
    key = "insert:%s:%s" % (op["palabra_es"], op["pagina"])
    row = con.execute("SELECT id FROM palabras WHERE palabra_es = ? AND pagina = ?",
                      (op["palabra_es"], op["pagina"])).fetchone()
    if row:
        id_map.setdefault(key, row[0])
        return "skipped"
    pid = next_id(con)
    con.execute("INSERT INTO palabras (id, palabra_es, palabra_norm, categoria_id, definicion_es, "
                "pagina, requiere_revision) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (pid, op["palabra_es"], palabra_norm(op["palabra_es"]),
                 category_id(con, op.get("categoria") or SIN_CATEGORIA, stats),
                 op.get("definicion_es") or "", op["pagina"]))
    if op.get("descripcion_sena"):
        set_field(con, pid, "descripcion_sena", op["descripcion_sena"], stats)
    con.execute("INSERT INTO rutas_imagenes (palabra_id, ruta_imagen, es_principal) VALUES (?, ?, 1)",
                (pid, image_path(pid)))
    id_map[key] = pid
    stats["new_ids"].append(pid)
    return "applied"


def repoint(con, old, new, synonyms):
    """Move every reference of row `old` to row `new` (DB synonyms and curated synonyms)."""
    have = {s for (s,) in con.execute("SELECT sinonimo_norm FROM sinonimos_mapeo WHERE palabra_id = ?",
                                      (new,))}
    for sid, syn in con.execute("SELECT id, sinonimo_norm FROM sinonimos_mapeo WHERE palabra_id = ?",
                                (old,)).fetchall():
        if syn in have:
            con.execute("DELETE FROM sinonimos_mapeo WHERE id = ?", (sid,))
        else:
            con.execute("UPDATE sinonimos_mapeo SET palabra_id = ? WHERE id = ?", (new, sid))
            have.add(syn)
    for entry in synonyms:
        if entry.get("palabra_id") == old:
            entry["palabra_id"] = new


def delete_row(con, pid):
    for table in ("sinonimos_mapeo", "senas_descripciones", "rutas_imagenes"):
        con.execute("DELETE FROM %s WHERE palabra_id = ?" % table, (pid,))
    con.execute("DELETE FROM palabras WHERE id = ?", (pid,))


def apply_merge(con, op, stats, id_map, synonyms):
    keep, frags, full = op["keep_id"], op["fragment_ids"], op["palabra_es_full"]
    if keep in frags or LETTER_IDS.intersection(frags):
        raise Conflict("%s: invalid fragment list %r" % (keep, frags))
    if not exists(con, keep):
        raise Conflict("%s: kept row does not exist" % keep)
    live = [f for f in frags if exists(con, f)]
    if not live and get_field(con, keep, "palabra_es") == full:
        for f in frags:
            id_map[f] = keep
        return "skipped"
    for field in ("categoria", "definicion_es", "descripcion_sena"):
        if is_empty(field, get_field(con, keep, field)):
            for f in live:
                value = get_field(con, f, field)
                if not is_empty(field, value):
                    set_field(con, keep, field, value, stats)
                    break
    set_field(con, keep, "palabra_es", full, stats)
    if not con.execute("SELECT 1 FROM rutas_imagenes WHERE palabra_id = ?", (keep,)).fetchone():
        con.execute("INSERT INTO rutas_imagenes (palabra_id, ruta_imagen, es_principal) VALUES (?, ?, 1)",
                    (keep, image_path(keep)))
    for f in live:
        repoint(con, f, keep, synonyms)
        delete_row(con, f)
    for f in frags:
        id_map[f] = keep
    stats["merged_ids"].append(keep)
    return "applied"


def apply_delete_divider(con, op, stats, id_map, synonyms):
    pid, letter = op["id"], op["repoint_to"]
    if pid in LETTER_IDS or letter not in LETTER_IDS:
        raise Conflict("%s: divider rows must repoint to a fingerspelling letter id" % pid)
    id_map[pid] = letter
    if not exists(con, pid):
        return "skipped"
    repoint(con, pid, letter, synonyms)
    delete_row(con, pid)
    return "applied"


def apply_add_synonym(con, op, stats):
    pid, syn = op["id"], op["sinonimo_norm"]
    if not exists(con, pid):
        raise Conflict("%s: row does not exist" % pid)
    owner = con.execute("SELECT palabra_id FROM sinonimos_mapeo WHERE sinonimo_norm = ?",
                        (syn,)).fetchone()
    if owner:
        if owner[0] != pid:
            raise Conflict("synonym %r already maps to %s" % (syn, owner[0]))
        return "skipped"
    con.execute("INSERT INTO sinonimos_mapeo (palabra_id, sinonimo_norm) VALUES (?, ?)", (pid, syn))
    return "applied"


# ----------------------------------------------------------------- reporting
def problem_counts(con):
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "rows": one("SELECT COUNT(*) FROM palabras"),
        "without_description": one(
            "SELECT COUNT(*) FROM palabras p WHERE NOT EXISTS (SELECT 1 FROM senas_descripciones s "
            "WHERE s.palabra_id = p.id AND TRIM(s.descripcion_sena) <> '')"),
        "without_definition": one(
            "SELECT COUNT(*) FROM palabras WHERE definicion_es IS NULL OR TRIM(definicion_es) = ''"),
        "sin_categoria": one(
            "SELECT COUNT(*) FROM palabras p LEFT JOIN categorias c ON c.id = p.categoria_id "
            "WHERE c.nombre IS NULL OR c.nombre = '%s'" % SIN_CATEGORIA),
        "split_headword_rows": one(
            "SELECT COUNT(*) FROM palabras WHERE palabra_es LIKE '(%' "
            "OR (palabra_es LIKE '%)' AND palabra_es NOT LIKE '%(%') "
            "OR (palabra_es LIKE '%(%' AND palabra_es NOT LIKE '%)') OR palabra_es LIKE '%,'"),
        "requiere_revision": one("SELECT COUNT(*) FROM palabras WHERE requiere_revision = 1"),
        "categories": one("SELECT COUNT(*) FROM categorias"),
    }


def recompute_revision(con, flagged):
    complete = 0
    for (pid,) in con.execute("SELECT id FROM palabras").fetchall():
        ok = pid not in flagged and all(
            not is_empty(f, get_field(con, pid, f))
            for f in ("categoria", "definicion_es", "descripcion_sena"))
        con.execute("UPDATE palabras SET requiere_revision = ? WHERE id = ?", (0 if ok else 1, pid))
        complete += ok
    return complete


def prune_categories(con):
    cur = con.execute("DELETE FROM categorias WHERE nombre <> ? AND id NOT IN "
                      "(SELECT DISTINCT categoria_id FROM palabras WHERE categoria_id IS NOT NULL)",
                      (SIN_CATEGORIA,))
    return cur.rowcount


# ----------------------------------------------------------------- main
def run(db_path, fixes_path, synonyms_path, dry_run=False, out=sys.stdout):
    with open(fixes_path, encoding="utf-8") as fh:
        fixes = json.load(fh)
    synonyms_doc = None
    if synonyms_path and os.path.exists(synonyms_path):
        with open(synonyms_path, encoding="utf-8") as fh:
            synonyms_doc = json.load(fh)
    synonyms = synonyms_doc["entries"] if synonyms_doc else []
    before_syn = json.dumps(synonyms, ensure_ascii=False, sort_keys=True)

    con = sqlite3.connect(db_path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = OFF")
    before = problem_counts(con)
    stats = {"categories_created": 0, "new_ids": [], "merged_ids": []}
    results = {}
    id_map = {}
    order = ("update", "insert", "merge_split", "delete_divider", "add_synonym", "flag")
    ops = sorted(fixes["ops"], key=lambda o: order.index(o["op"]))
    flagged = {o["id"] for o in ops if o["op"] == "flag"}
    con.execute("BEGIN")
    try:
        for op in ops:
            kind = op["op"]
            if kind == "update":
                res = apply_update(con, op, stats)
            elif kind == "insert":
                res = apply_insert(con, op, stats, id_map)
            elif kind == "merge_split":
                res = apply_merge(con, op, stats, id_map, synonyms)
            elif kind == "delete_divider":
                res = apply_delete_divider(con, op, stats, id_map, synonyms)
            elif kind == "add_synonym":
                res = apply_add_synonym(con, op, stats)
            elif kind == "flag":
                if not exists(con, op["id"]):
                    raise Conflict("%s: flagged row does not exist" % op["id"])
                res = "skipped" if con.execute("SELECT requiere_revision FROM palabras WHERE id = ?",
                                               (op["id"],)).fetchone()[0] else "applied"
            else:
                raise Conflict("unknown op %r" % kind)
            results.setdefault(kind, {"applied": 0, "skipped": 0})[res] += 1
        missing = [pid for pid in LETTER_IDS if not exists(con, pid)]
        if missing:
            raise Conflict("fingerspelling ids missing: %s" % ", ".join(sorted(missing)))
        complete = recompute_revision(con, flagged)
        pruned = prune_categories(con)
        after = problem_counts(con)
        if dry_run:
            con.execute("ROLLBACK")
        else:
            con.execute("COMMIT")
    except Conflict as exc:
        con.execute("ROLLBACK")
        con.close()
        print("CONFLICT, nothing written: %s" % exc, file=out)
        return 2
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        raise
    if not dry_run:
        con.execute("VACUUM")
    con.close()

    synonyms_changed = json.dumps(synonyms, ensure_ascii=False, sort_keys=True) != before_syn
    if not dry_run:
        if synonyms_changed:
            with open(synonyms_path, "w", encoding="utf-8") as fh:
                json.dump(synonyms_doc, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        if fixes.get("id_map") != dict(sorted(id_map.items())):
            fixes["id_map"] = dict(sorted(id_map.items()))
            with open(fixes_path, "w", encoding="utf-8") as fh:
                json.dump(fixes, fh, ensure_ascii=False, indent=1)
                fh.write("\n")

    print("%s %s" % ("DRY RUN (rolled back):" if dry_run else "Applied:", db_path), file=out)
    for kind in order:
        if kind in results:
            print("  %-15s applied %4d  skipped %4d" % (kind, results[kind]["applied"],
                                                       results[kind]["skipped"]), file=out)
    print("  categories created %d, unreferenced categories removed %d"
          % (stats["categories_created"], pruned), file=out)
    print("  complete rows (requiere_revision=0): %d" % complete, file=out)
    print("  curated synonyms repointed: %s" % ("yes" if synonyms_changed else "no"), file=out)
    print("  %-22s %8s %8s" % ("known problem", "before", "after"), file=out)
    for k in before:
        print("  %-22s %8d %8d" % (k, before[k], after[k]), file=out)
    if stats["merged_ids"] or stats["new_ids"]:
        print("  ids needing new images: %s" % " ".join(sorted(set(stats["merged_ids"] + stats["new_ids"]))),
              file=out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=os.path.join(ROOT, "lsrd_dictionary.db"))
    ap.add_argument("--fixes", default=os.path.join(ROOT, "data", "dictionary_fixes.json"))
    ap.add_argument("--synonyms", default=os.path.join(ROOT, "data", "synonyms_extra.json"),
                    help="curated synonyms whose palabra_id values follow merged/deleted rows")
    ap.add_argument("--dry-run", action="store_true", help="report only, roll everything back")
    args = ap.parse_args(argv)
    return run(args.db, args.fixes, args.synonyms, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
