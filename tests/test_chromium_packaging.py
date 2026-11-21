import tempfile
import unittest
from pathlib import Path

from theodoro.browser import ChromiumUnavailable, chromium_executable


class BundledChromiumTests(unittest.TestCase):
    def test_frozen_browser_must_exist_inside_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            bundled = root / '_internal' / 'browsers'
            expected = bundled / 'chromium-1194' / 'chrome-win' / 'chrome.exe'
            external = root / 'chrome.exe'
            external.touch()

            with self.assertRaisesRegex(ChromiumUnavailable, 'não encontrado na distribuição'):
                chromium_executable(expected, bundled, external)
            with self.assertRaises(ChromiumUnavailable):
                chromium_executable(external, bundled, None)

            expected.parent.mkdir(parents=True)
            expected.touch()
            self.assertEqual(chromium_executable(expected, bundled, external), expected)
