"""Checks for the entries recovered from the official dictionary PDF and DB integrity.

The recovered rows were inserted by tools/recover_dictionary_entries.py (see
docs/DICTIONARY_GAPS.md). Sign images are not tracked in git, so the image test only runs
when the local extracted_images/ folder is present.
"""
import json
import os
import sqlite3
import unicodedata
import unittest

import _common
import nlp_engine
import translator

DB_PATH = os.path.join(_common.ROOT, "lsrd_dictionary.db")
IMAGES_DIR = os.path.join(_common.ROOT, "extracted_images")
SYNONYMS_PATH = os.path.join(_common.ROOT, "data", "synonyms_extra.json")

# id -> (palabra_es, PDF page). Ids must never change once published.
RECOVERED = {
    "lsrd_2459": ("DICCIONARIO", 143),
    "lsrd_2460": ("GRANDE", 196),
    "lsrd_2461": ("GRANIZO", 196),
    "lsrd_2462": ("GRAPA", 196),
    "lsrd_2463": ("GRAPADORA", 196),
    "lsrd_2464": ("GRAPAR", 196),
    "lsrd_2465": ("GRITAR", 197),
    "lsrd_2466": ("GROSERO, RA", 197),
    "lsrd_2467": ("GRÚA", 197),
    "lsrd_2468": ("GUANDUL", 198),
    "lsrd_2469": ("GUANTE", 198),
    "lsrd_2470": ("GUANTE (DEPORTE)", 198),
    "lsrd_2471": ("GUERRA", 199),
    "lsrd_2472": ("GUIAR", 199),
    "lsrd_2473": ("GUINEO", 199),
    "lsrd_2474": ("LOCRIO DE POLLO", 414),
    "lsrd_2475": ("MANGA CORTA", 414),
    "lsrd_2476": ("MANGA LARGA", 414),
}

# Rows of the original extraction without a movement description: entries that share one
# description with the next headword (only the last one got it), alphabet letters and the
# regional-signs section. New rows must not add to this number.
MAX_ROWS_WITHOUT_DESCRIPTION = 256


def _norm(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if unicodedata.category(c) != "Mn").strip()


class RecoveredEntriesTranslateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr = translator.LSRDTranslator()
        cls.nlp = nlp_engine.LSRDNlpEngine()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()

    def test_recovered_words_are_lexical_signs(self):
        cases = {"grande": "lsrd_2460", "granizo": "lsrd_2461", "gritar": "lsrd_2465",
                 "grosero": "lsrd_2466", "grua": "lsrd_2467", "guante": "lsrd_2469",
                 "guerra": "lsrd_2471", "guiar": "lsrd_2472", "guineo": "lsrd_2473",
                 "diccionario": "lsrd_2459", "grapadora": "lsrd_2463"}
        for word, pid in cases.items():
            with self.subTest(word=word):
                out = self.tr.translate_sequence([word])
                self.assertEqual(len(out), 1)
                self.assertFalse(out[0]["es_deletreo"])
                self.assertEqual(out[0]["match_method"], "exact")
                self.assertEqual(out[0]["id"], pid)

    def test_sentence_uses_recovered_sign(self):
        seq = self.nlp.process("La casa es muy grande")["secuencia_lsrd"]
        signs = self.tr.translate_sequence(seq)
        self.assertIn("lsrd_2460", [s["id"] for s in signs])

    def test_multiword_recovered_entry(self):
        seq = self.nlp.process("Quiero una camisa de manga corta")["secuencia_lsrd"]
        ids = [s["id"] for s in self.tr.translate_sequence(seq)]
        self.assertIn("lsrd_2475", ids)


class DictionaryIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def q(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()

    def test_recovered_rows_complete(self):
        for pid, (palabra, page) in RECOVERED.items():
            with self.subTest(pid=pid):
                row = self.q("SELECT palabra_es, palabra_norm, pagina, categoria_id, definicion_es "
                             "FROM palabras WHERE id = ?", pid)
                self.assertEqual(len(row), 1)
                es, norm, pagina, cat, definition = row[0]
                self.assertEqual((es, pagina), (palabra, page))
                self.assertEqual(norm, _norm(es))
                self.assertIsNotNone(cat)
                self.assertTrue(definition)
                desc = self.q("SELECT descripcion_sena FROM senas_descripciones WHERE palabra_id = ?", pid)
                self.assertEqual(len(desc), 1)
                self.assertGreater(len(desc[0][0]), 20)
                self.assertEqual(self.q("SELECT ruta_imagen FROM rutas_imagenes WHERE palabra_id = ?", pid),
                                 [(f"extracted_images/{pid}.png",)])

    def test_every_row_has_an_image_path(self):
        self.assertEqual(self.q("SELECT id FROM palabras WHERE id NOT IN "
                                "(SELECT palabra_id FROM rutas_imagenes)"), [])

    def test_rows_without_description_do_not_grow(self):
        n = self.q("SELECT COUNT(*) FROM palabras WHERE id NOT IN "
                   "(SELECT palabra_id FROM senas_descripciones)")[0][0]
        self.assertLessEqual(n, MAX_ROWS_WITHOUT_DESCRIPTION)

    def test_no_duplicate_or_dangling_ids(self):
        self.assertEqual(self.q("SELECT id FROM palabras GROUP BY id HAVING COUNT(*) > 1"), [])
        self.assertEqual(self.q("SELECT palabra_id FROM rutas_imagenes GROUP BY palabra_id "
                                "HAVING COUNT(*) > 1"), [])
        for table in ("senas_descripciones", "rutas_imagenes", "sinonimos_mapeo"):
            with self.subTest(table=table):
                self.assertEqual(self.q(f"SELECT palabra_id FROM {table} WHERE palabra_id NOT IN "
                                        "(SELECT id FROM palabras)"), [])

    def test_ids_are_contiguous(self):
        # Rows merged or deleted by data/dictionary_fixes.json leave gaps, recorded
        # in its id_map (old id -> surviving id); no other gap is allowed.
        with open(os.path.join(_common.ROOT, "data", "dictionary_fixes.json"),
                  encoding="utf-8") as fh:
            removed = {int(pid.split("_")[1]) for pid in json.load(fh)["id_map"]}
        nums = sorted(int(pid.split("_")[1]) for (pid,) in self.q("SELECT id FROM palabras"))
        self.assertEqual(sorted(set(nums) | removed), list(range(1, max(nums) + 1)))
        self.assertEqual(set(nums) & removed, set())

    def test_norm_matches_spelling(self):
        bad = [(es, norm) for es, norm in self.q("SELECT palabra_es, palabra_norm FROM palabras")
               if norm != _norm(es)]
        self.assertEqual(bad, [])

    def test_fingerspelling_ids_still_exist(self):
        for letter, pid in translator.DACTYL_LETTER_MAP.items():
            with self.subTest(letter=letter):
                row = self.q("SELECT palabra_es FROM palabras WHERE id = ?", pid)
                self.assertEqual(len(row), 1)
                self.assertEqual(row[0][0], letter.upper())

    def test_curated_synonyms_point_to_existing_signs(self):
        with open(SYNONYMS_PATH, encoding="utf-8") as fh:
            entries = json.load(fh)["entries"]
        for e in entries:
            with self.subTest(word=e["word"]):
                self.assertIn(e.get("source"), ("curated", "curated-pending-review"))
                row = self.q("SELECT palabra_norm FROM palabras WHERE id = ?", e["palabra_id"])
                self.assertEqual(len(row), 1)
                self.assertEqual(row[0][0].split(",")[0].strip(), e["target_norm"])

    @unittest.skipUnless(os.path.isdir(IMAGES_DIR), "extracted_images/ is not present (not in git)")
    def test_recovered_images_exist(self):
        for pid in RECOVERED:
            with self.subTest(pid=pid):
                path = os.path.join(IMAGES_DIR, f"{pid}.png")
                self.assertTrue(os.path.isfile(path))
                with open(path, "rb") as fh:
                    self.assertEqual(fh.read(8), b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
