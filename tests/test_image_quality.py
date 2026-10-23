"""Quality gate for the local sign images (extracted_images/lsrd_XXXX.png).

Every LSRD illustration shows a person signing, drawn with flat skin-tone hands and face.
A crop with (almost) no skin-tone pixels shows dictionary text or blank paper instead of
the drawing: the original extraction produced ~1,200 of those. They are regenerated from
the official PDF with tools/recrop_sign_images.py (see docs/IMAGES.md).

Images are not tracked in git, so the test is skipped when the folder is absent (CI).
"""
import os
import sqlite3
import sys
import unittest

import _common

sys.path.insert(0, os.path.join(_common.ROOT, "tools"))
from recrop_sign_images import SKIN_THRESHOLD, skin_score  # noqa: E402

DB_PATH = os.path.join(_common.ROOT, "lsrd_dictionary.db")
IMAGES_DIR = os.environ.get("BIBLIONX_IMAGES_DIR") or os.path.join(_common.ROOT, "extracted_images")

# Entries whose official illustration genuinely has (almost) no skin-tone pixels.
# Each item must say why. Empty: after regeneration every illustration passes.
ALLOWLIST = {}


@unittest.skipUnless(os.path.isdir(IMAGES_DIR), "extracted_images/ not present (not in git)")
class ImageQualityTest(unittest.TestCase):
    def test_referenced_images_show_a_signer(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            paths = conn.execute(
                "SELECT palabra_id, ruta_imagen FROM rutas_imagenes "
                "WHERE ruta_imagen LIKE 'extracted_images/lsrd_%.png' ORDER BY palabra_id").fetchall()
        finally:
            conn.close()
        self.assertGreater(len(paths), 2000)
        missing, low = [], []
        for pid, path in paths:
            full = os.path.join(IMAGES_DIR, os.path.basename(path))
            if not os.path.exists(full):
                missing.append(pid)
                continue
            score = skin_score(full)
            if (score is None or score < SKIN_THRESHOLD) and pid not in ALLOWLIST:
                low.append((pid, score))
        self.assertEqual(missing, [], "referenced images missing on disk")
        self.assertEqual(low, [], "images without a signer (text-only crops?); "
                                  "regenerate with tools/recrop_sign_images.py")

    def test_skin_rule_on_synthetic_pixels(self):
        from recrop_sign_images import is_skin
        self.assertTrue(is_skin(240, 210, 165))       # illustration skin tone
        self.assertFalse(is_skin(255, 255, 255))      # paper
        self.assertFalse(is_skin(0, 102, 153))        # headword blue
        self.assertFalse(is_skin(60, 60, 60))         # body text


if __name__ == "__main__":
    unittest.main()
