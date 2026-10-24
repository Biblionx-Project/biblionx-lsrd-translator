"""Integrity checks for lsrd_dictionary.db after the v2.3 dictionary completion.

The fixes come from a page-by-page audit of the official PDF and are applied by
tools/apply_dictionary_fixes.py from data/dictionary_fixes.json. Rows the PDF itself leaves
incomplete (no definition printed, no category printed) are listed there as 'flag' ops.
"""
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest

import _common
import translator
from tools import apply_dictionary_fixes as fixes_tool

DB_PATH = os.path.join(_common.ROOT, "lsrd_dictionary.db")
FIXES_PATH = os.path.join(_common.ROOT, "data", "dictionary_fixes.json")
SYNONYMS_PATH = os.path.join(_common.ROOT, "data", "synonyms_extra.json")

FIRST_ENTRY_PAGE = 29   # PDF pages 1-28 are front matter
# The PDF has 437 pages (two-page spreads). Pages 428-436 hold the pronoun and province
# annexes; page 437 is the back cover.
LAST_ENTRY_PAGE = 436
SIN_CATEGORIA = "Sin Categoría"


class DictionaryIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)
        with open(FIXES_PATH, encoding="utf-8") as fh:
            cls.fixes = json.load(fh)
        cls.flagged = {o["id"] for o in cls.fixes["ops"] if o["op"] == "flag"}

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def q(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    def test_ids_are_unique_and_well_formed(self):
        ids = [r[0] for r in self.q("SELECT id FROM palabras")]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r"lsrd_\d{4}", i) for i in ids))

    def test_one_description_and_one_image_per_row(self):
        for table in ("senas_descripciones", "rutas_imagenes"):
            with self.subTest(table=table):
                dupes = self.q("SELECT palabra_id FROM %s GROUP BY palabra_id HAVING COUNT(*) > 1" % table)
                self.assertEqual(dupes, [])

    def test_every_row_is_complete_unless_flagged(self):
        rows = self.q(
            "SELECT p.id, c.nombre, p.definicion_es, "
            "(SELECT descripcion_sena FROM senas_descripciones s WHERE s.palabra_id = p.id) "
            "FROM palabras p LEFT JOIN categorias c ON c.id = p.categoria_id")
        incomplete = [pid for pid, cat, dfn, desc in rows
                      if cat in (None, "", SIN_CATEGORIA) or not (dfn or "").strip()
                      or not (desc or "").strip()]
        self.assertEqual(sorted(set(incomplete) - self.flagged), [])

    def test_every_row_has_a_movement_description(self):
        missing = self.q("SELECT id FROM palabras p WHERE NOT EXISTS (SELECT 1 FROM "
                         "senas_descripciones s WHERE s.palabra_id = p.id AND TRIM(s.descripcion_sena) <> '')")
        self.assertEqual(missing, [])

    def test_requiere_revision_matches_completeness(self):
        for pid, rev in self.q("SELECT id, requiere_revision FROM palabras"):
            if pid in self.flagged:
                self.assertEqual(rev, 1, pid)

    def test_flags_point_to_existing_rows(self):
        existing = {r[0] for r in self.q("SELECT id FROM palabras")}
        self.assertEqual(sorted(self.flagged - existing), [])

    def test_fingerspelling_ids_intact(self):
        for letter, pid in translator.DACTYL_LETTER_MAP.items():
            with self.subTest(letter=letter):
                row = self.q("SELECT palabra_es FROM palabras WHERE id = ?", (pid,))
                self.assertEqual(len(row), 1)
                self.assertEqual(row[0][0].lower(), letter)
                self.assertTrue(self.q("SELECT 1 FROM senas_descripciones WHERE palabra_id = ?", (pid,)))
        self.assertEqual(set(translator.DACTYL_LETTER_MAP.values()), set(fixes_tool.LETTER_IDS))

    def test_single_letters_resolve_to_the_alphabet_sign(self):
        # Rows built from letter-divider pages (B, C, D, E, F, G) were removed.
        rows = self.q("SELECT id, palabra_norm FROM palabras WHERE LENGTH(palabra_norm) = 1")
        letters = set(translator.DACTYL_LETTER_MAP.values())
        self.assertEqual([r for r in rows if r[0] not in letters], [])

    def test_image_paths_match_ids(self):
        bad = self.q("SELECT palabra_id, ruta_imagen FROM rutas_imagenes "
                     "WHERE ruta_imagen <> 'extracted_images/' || palabra_id || '.png'")
        self.assertEqual(bad, [])
        no_image = self.q("SELECT id FROM palabras p WHERE NOT EXISTS "
                          "(SELECT 1 FROM rutas_imagenes r WHERE r.palabra_id = p.id)")
        self.assertEqual(no_image, [])

    def test_no_orphan_references(self):
        for table in ("senas_descripciones", "rutas_imagenes", "sinonimos_mapeo"):
            with self.subTest(table=table):
                orphans = self.q("SELECT palabra_id FROM %s WHERE palabra_id NOT IN "
                                 "(SELECT id FROM palabras)" % table)
                self.assertEqual(orphans, [])
        existing = {r[0] for r in self.q("SELECT id FROM palabras")}
        with open(SYNONYMS_PATH, encoding="utf-8") as fh:
            curated = json.load(fh)["entries"]
        dangling = [e for e in curated if e.get("palabra_id") and e["palabra_id"] not in existing]
        self.assertEqual(dangling, [])
        unused = self.q("SELECT nombre FROM categorias WHERE nombre <> ? AND id NOT IN "
                        "(SELECT categoria_id FROM palabras WHERE categoria_id IS NOT NULL)",
                        (SIN_CATEGORIA,))
        self.assertEqual(unused, [])

    def test_pages_are_within_the_pdf(self):
        out = self.q("SELECT id, pagina FROM palabras WHERE pagina < ? OR pagina > ?",
                     (FIRST_ENTRY_PAGE, LAST_ENTRY_PAGE))
        self.assertEqual(out, [])

    def test_no_split_headwords(self):
        rows = self.q("SELECT id, palabra_es, palabra_norm FROM palabras")
        for pid, es, norm in rows:
            with self.subTest(id=pid, palabra_es=es):
                self.assertFalse(es.startswith("("))
                self.assertFalse(es.rstrip().endswith(","))
                self.assertEqual(es.count("("), es.count(")"))
                self.assertEqual(norm, fixes_tool.palabra_norm(es))

    def test_no_stray_illustration_step_digits(self):
        rows = self.q("SELECT p.id, c.nombre, p.definicion_es FROM palabras p "
                      "LEFT JOIN categorias c ON c.id = p.categoria_id")
        for pid, cat, dfn in rows:
            for value in (cat or "", dfn or ""):
                with self.subTest(id=pid):
                    self.assertIsNone(re.match(r"\d+\s+[^\d.]", value), value)
                    self.assertIsNone(re.search(r"\s\d+\s*$", value), value)

    def test_id_map_targets_exist_and_sources_are_gone(self):
        existing = {r[0] for r in self.q("SELECT id FROM palabras")}
        for old, new in self.fixes["id_map"].items():
            with self.subTest(old=old):
                self.assertNotIn(old, existing)
                self.assertIn(new, existing)

    def test_fixes_are_already_applied(self):
        """Re-running the fix tool on a copy changes nothing (idempotent, fully applied)."""
        tmp = tempfile.mkdtemp()
        try:
            db = os.path.join(tmp, "lsrd_dictionary.db")
            shutil.copyfile(DB_PATH, db)
            out = io.StringIO()
            rc = fixes_tool.run(db, FIXES_PATH, SYNONYMS_PATH, dry_run=True, out=out)
            self.assertEqual(rc, 0, out.getvalue())
            applied = re.findall(r"applied\s+(\d+)", out.getvalue())
            self.assertTrue(applied)
            self.assertTrue(all(n == "0" for n in applied), out.getvalue())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class MergedEntriesTranslateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr = translator.LSRDTranslator()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()

    def test_province_names_reach_the_province_sign(self):
        cases = {"santiago": "lsrd_2455", "la vega": "lsrd_2422", "nagua": "lsrd_2425",
                 "bonao": "lsrd_2427", "azua": "lsrd_2395", "santiago de los caballeros": "lsrd_2455"}
        for word, pid in cases.items():
            with self.subTest(word=word):
                out = self.tr.translate_sequence([word])
                self.assertEqual([s["id"] for s in out], [pid])

    def test_merged_head_words_stay_reachable(self):
        for word, pid in {"tarjeta": "lsrd_2054", "secador": "lsrd_1936", "aji": "lsrd_0097",
                          "b": "lsrd_0262"}.items():
            with self.subTest(word=word):
                out = self.tr.translate_sequence([word])
                self.assertEqual([s["id"] for s in out], [pid])


if __name__ == "__main__":
    unittest.main()
