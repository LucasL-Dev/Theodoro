import os
import sys
from pathlib import Path

BROWSERS = {
    'chrome': 'Google Chrome',
    'msedge': 'Microsoft Edge',
    'chromium': 'Chromium integrado',
}

WINDOWS_PATHS = {
    'chrome': ('Google', 'Chrome', 'Application', 'chrome.exe'),
    'msedge': ('Microsoft', 'Edge', 'Application', 'msedge.exe'),
}
OTHER_PATHS = {
    'linux': {'chrome': '/opt/google/chrome/chrome', 'msedge': '/opt/microsoft/msedge/msedge'},
    'darwin': {
        'chrome': '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        'msedge': '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    },
}


def installed_channel(channel):
    """Check the standard locations resolved by Playwright's stable channels."""
    if sys.platform == 'win32':
        roots = [os.environ.get(name) for name in ('LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)')]
        drive = os.environ.get('HOMEDRIVE')
        if drive:
            roots.extend((drive + r'\Program Files', drive + r'\Program Files (x86)'))
        options = (Path(root).joinpath(*WINDOWS_PATHS[channel]) for root in roots if root)
        return any(path.is_file() for path in options)
    location = OTHER_PATHS.get(sys.platform, {}).get(channel)
    return bool(location and Path(location).is_file())


def default_browser():
    return 'chrome' if sys.platform == 'win32' and installed_channel('chrome') else 'chromium'
