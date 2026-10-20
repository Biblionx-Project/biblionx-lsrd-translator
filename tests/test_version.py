"""The single VERSION file must agree with every versioned artifact."""
import os
import subprocess
import sys
import unittest

try:
    import _common
except ModuleNotFoundError:
    from tests import _common

SCRIPT = os.path.join(_common.ROOT, "scripts", "check_version.py")


class VersionTests(unittest.TestCase):
    def test_all_versions_match(self):
        sys.path.insert(0, os.path.join(_common.ROOT, "scripts"))
        try:
            import check_version
            self.assertEqual(check_version.check(), [])
        finally:
            sys.path.pop(0)

    def test_script_exit_codes(self):
        ok = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_mismatch_detected(self):
        sys.path.insert(0, os.path.join(_common.ROOT, "scripts"))
        try:
            import check_version
            real = check_version.collect
            check_version.collect = lambda: ("9.9.9", {"x": "2.2.0"})
            try:
                self.assertTrue(check_version.check())
                self.assertEqual(check_version.main(), 1)
            finally:
                check_version.collect = real
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
