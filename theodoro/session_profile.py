import csv
import re
import stat
import subprocess
import sys
from pathlib import Path

from .browser_choices import BROWSERS


def plain_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError('A pasta de sessão deve ser local e não pode ser um link ou redirecionamento.')


def protected_profile(root, choice):
    if choice not in BROWSERS:
        raise ValueError('Navegador inválido para o perfil de sessão.')
    root = Path(root)
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        plain_directory(root)
    else:
        try:
            if sys.platform == 'win32':
                options = dict(check=True, capture_output=True, text=True, errors='replace', timeout=15,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                account = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'], **options)
                sid = next(csv.reader(account.stdout.splitlines()))[1]
                if not re.fullmatch(r'S-1-[0-9-]+', sid):
                    raise ValueError('Não foi possível identificar a conta Windows para proteger a sessão.')
                subprocess.run([
                    'icacls.exe', str(root), '/grant:r', f'*{sid}:(OI)(CI)F',
                    '*S-1-5-18:(OI)(CI)F', '/inheritance:r',
                ], **options)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, StopIteration):
            root.rmdir()
            raise ValueError('Não foi possível proteger a pasta de sessão do Theodoro.') from None
    if sys.platform != 'win32':
        root.chmod(0o700)
    profile = root / choice
    profile.mkdir(mode=0o700, exist_ok=True)
    plain_directory(profile)
    if sys.platform != 'win32':
        profile.chmod(0o700)
    return profile
