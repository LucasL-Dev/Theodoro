import sys
import os

# PyInstaller bundles Chromium into Playwright's package-local browser directory.
if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

from theodoro.desktop import main

if __name__ == '__main__':
    raise SystemExit(main())
