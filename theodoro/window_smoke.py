"""Emulate manual Chrome launch from outside the accessibility adapter."""
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep

from .browser_choices import channel_executable
from .open_window import DEMO_PATH, OpenChrome


def verify_open_chrome():
    adapter = OpenChrome(Event())
    with TemporaryDirectory() as folder:
        chrome = subprocess.Popen([
            str(channel_executable('chrome')),
            f'--user-data-dir={Path(folder) / "chrome"}', '--no-first-run',
            '--new-window', DEMO_PATH.resolve().as_uri(),
        ])
        try:
            selected = None
            deadline = monotonic() + 20
            last_error = None
            while monotonic() < deadline:
                try:
                    for handle, pid, _ in adapter.windows():
                        if pid != chrome.pid:
                            continue
                        candidate = (handle, pid)
                        fields, token = adapter.inspect(candidate, True)
                        if 'Vendas líquidas' in fields:
                            selected = candidate
                            break
                except Exception as error:
                    last_error = error
                if selected:
                    break
                sleep(0.5)
            if selected is None:
                raise RuntimeError('O formulário fictício em Chrome externo não foi acessível.') from last_error
            result = adapter.fill(
                selected, True, {'net': 'Vendas líquidas', 'sale_date': 'Data da venda'},
                {'net': 13000, 'sale_date': '2026-11-20'}, 'br', token,
            )
            if result != {'net': '130,00', 'sale_date': '20/11/2026'}:
                raise RuntimeError('A releitura dos controles de acessibilidade divergiu.')
        finally:
            chrome.terminate()
            chrome.wait(timeout=10)
