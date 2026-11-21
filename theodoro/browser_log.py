import logging
import re
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger('theodoro.browser')

SAFE_DETAILS = (
    'Target page, context or browser has been closed', 'Browser closed', 'Timeout',
    'ProcessSingleton', 'SingletonLock', 'profile in use', 'user data directory is already in use',
    'Access is denied', 'Permission denied', 'Executable doesn\'t exist', 'not found',
    'DevToolsActivePort', 'ECONNREFUSED', 'ENOENT', 'EACCES', 'ETIMEDOUT',
)


def configure_log(directory):
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / 'browser.log', maxBytes=512_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_error(stage, error):
    """Record the original exception chain without interpolating portal content or launch arguments."""
    while error is not None:
        original = str(error)
        details = [detail for detail in SAFE_DETAILS if detail.casefold() in original.casefold()]
        details.extend(sorted(set(re.findall(r'\bnet::ERR_[A-Z0-9_]+\b', original))))
        frames = ' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
                            for frame in traceback.extract_tb(error.__traceback__))
        logger.warning('etapa=%s exceção=%s sinais=%s origem=%s',
                       stage, type(error).__name__, ', '.join(details) or 'sem código seguro', frames)
        error = error.__cause__
