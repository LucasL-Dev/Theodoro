"""Exercise an independently launched Chrome through native Windows accessibility."""
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep

from .browser_choices import channel_executable
from .open_window import AccessibilityUnavailable, DEMO_PATH, OpenChrome

EXPECTED = {'net': '130,00', 'sale_date': '20/11/2026'}


def wait_for_window(adapter, pid, excluded=()):
    deadline = monotonic() + 15
    while monotonic() < deadline:
        windows = [(handle, owner) for handle, owner, _ in adapter.windows()
                   if owner == pid and handle not in excluded]
        if len(windows) == 1:
            return windows[0]
        sleep(0.4)
    raise RuntimeError('O teste não encontrou a janela Chrome esperada.')


def inspect_fixture(adapter, selected):
    deadline = monotonic() + 15
    while True:
        try:
            fields, token = adapter.inspect(selected, True)
            break
        except AccessibilityUnavailable:
            if monotonic() >= deadline:
                raise
            sleep(0.4)
    if not {'Vendas líquidas', 'Data da venda'}.issubset(fields):
        raise RuntimeError('Os campos do documento principal não foram expostos.')
    if 'Campo aninhado' in fields:
        raise RuntimeError('Um campo do iframe foi confundido com o formulário principal.')
    return token


def verify_open_chrome():
    import win32con
    import win32gui

    adapter = OpenChrome(Event())
    with TemporaryDirectory() as folder:
        command = [
            str(channel_executable('chrome')),
            f'--user-data-dir={Path(folder) / "chrome"}', '--no-first-run',
            '--new-window',
        ]
        chrome = subprocess.Popen([*command, DEMO_PATH.resolve().as_uri()])
        try:
            selected = wait_for_window(adapter, chrome.pid)
            token = inspect_fixture(adapter, selected)
            result = adapter.fill(
                selected, True, {'net': 'Vendas líquidas', 'sale_date': 'Data da venda'},
                {'net': 13000, 'sale_date': '2026-11-20'}, 'br', token,
            )
            if result != EXPECTED:
                raise RuntimeError('A releitura da janela única divergiu.')
            subprocess.Popen([*command, 'about:blank'])
            other = wait_for_window(adapter, chrome.pid, excluded=(selected[0],))
            try:
                adapter.inspect(other, True)
            except AccessibilityUnavailable:
                pass
            else:
                raise RuntimeError('O teste aceitou a outra janela do Chrome.')
            token = inspect_fixture(adapter, selected)
            result = adapter.fill(
                selected, True, {'net': 'Vendas líquidas', 'sale_date': 'Data da venda'},
                {'net': 13000, 'sale_date': '2026-11-20'}, 'br', token,
            )
            if result != EXPECTED:
                raise RuntimeError('A releitura com múltiplas janelas divergiu.')
        finally:
            try:
                for handle, pid, _ in adapter.windows():
                    if pid == chrome.pid:
                        win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
                chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                chrome.kill()
                chrome.wait(timeout=10)
