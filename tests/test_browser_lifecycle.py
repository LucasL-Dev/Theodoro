import os
import unittest

from theodoro.browser_log import log_error


class BrowserLifecycleTests(unittest.TestCase):
    def test_exception_log_keeps_original_type_and_drops_sensitive_values(self):
        error = RuntimeError('net::ERR_CONNECTION_RESET user@empresa.test senha=confidencial')
        with self.assertLogs('theodoro.browser', level='WARNING') as captured:
            log_error('navegação_premier', error)
        self.assertIn('RuntimeError', captured.output[0])
        self.assertIn('net::ERR_CONNECTION_RESET', captured.output[0])
        self.assertNotIn('confidencial', captured.output[0])
        self.assertNotIn('empresa.test', captured.output[0])

    @unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium')
    def test_qt_worker_keeps_diagnostic_alive_across_actions(self):
        from PySide6.QtWidgets import QApplication
        from theodoro.browser_ui_smoke import verify_worker_browser

        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        app = QApplication.instance() or QApplication([])
        verify_worker_browser('chromium', headless=True)
