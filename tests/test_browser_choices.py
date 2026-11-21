import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from theodoro.browser import Browser, BrowserUnavailable
from theodoro.browser_choices import default_browser, installed_channel


class BrowserSelectionTests(unittest.TestCase):
    def test_official_windows_installations_and_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('theodoro.browser_choices.sys.platform', 'win32'), patch.dict(
                os.environ, {'LOCALAPPDATA': directory}, clear=True,
            ):
                self.assertEqual(default_browser(), 'chromium')
                chrome = Path(directory, 'Google', 'Chrome', 'Application', 'chrome.exe')
                chrome.parent.mkdir(parents=True)
                chrome.touch()
                self.assertTrue(installed_channel('chrome'))
                self.assertFalse(installed_channel('msedge'))
                self.assertEqual(default_browser(), 'chrome')

    def test_missing_channel_reports_selected_browser(self):
        browser = Browser(Event(), choice='msedge')
        with patch('theodoro.browser.channel_executable', return_value=None):
            with self.assertRaisesRegex(BrowserUnavailable, 'Microsoft Edge não encontrado'):
                browser.start()

    @unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium')
    def test_diagnostic_and_restart_preserve_then_discard_session(self):
        browser = Browser(Event(), headless=True)
        self.addCleanup(browser.close)
        self.assertTrue(browser.diagnose())
        page = browser.page('ifood', True)
        browser.context.add_cookies([{
            'name': 'teste', 'value': 'isolado', 'url': 'https://example.test/',
        }])
        self.assertTrue(browser.diagnose())
        self.assertFalse(page.is_closed())
        self.assertTrue(browser.context.cookies())
        browser.close()
        self.assertTrue(page.is_closed())
        self.assertTrue(browser.diagnose())
        self.assertEqual(browser.context.cookies(), [])
