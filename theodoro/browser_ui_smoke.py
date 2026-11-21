"""Run two browser actions separated by a return to the Qt event loop."""
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Qt, QTimer, Slot

from .desktop import Worker


class DiagnosticLoop(QObject):
    def __init__(self, requests):
        super().__init__()
        self.requests = requests
        self.loop = QEventLoop()
        self.error = 'O diagnóstico visual não retornou em tempo hábil.'

    @Slot(str, object)
    def completed(self, action, result):
        if 'error' in result:
            self.error = result['error']
            self.loop.quit()
        elif action == 'browser_test':
            QTimer.singleShot(1200, self.verify)
        elif action == 'browser_verify':
            self.error = None
            self.loop.quit()

    def verify(self):
        self.requests.put(('browser_verify', None))


def verify_worker_browser(channel, *, headless):
    app = QCoreApplication.instance() or QCoreApplication([])
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        stop = Event()
        requests = Queue()
        worker = Worker(stop, directory / 'test.sqlite', channel, directory / 'sessions')
        worker.browser.headless = headless
        diagnostic = DiagnosticLoop(requests)
        worker.done.connect(diagnostic.completed, Qt.ConnectionType.QueuedConnection)
        thread = Thread(target=worker.serve, args=(requests,))
        thread.start()
        try:
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(diagnostic.loop.quit)
            timeout.start(35000)
            requests.put(('browser_test', None))
            diagnostic.loop.exec()
            timeout.stop()
            if diagnostic.error:
                raise RuntimeError(diagnostic.error)
        finally:
            stop.set()
            requests.put(('close', None))
            thread.join()
