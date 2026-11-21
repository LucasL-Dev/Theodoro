import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from queue import Queue
from threading import Event, Thread

from PySide6.QtCore import QDate, QObject, QStandardPaths, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDateEdit, QFileDialog, QHBoxLayout, QLabel,
    QInputDialog, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from playwright.sync_api import Error as PlaywrightError

from financeiro.mapping import Entry
from financeiro.sync import History

from .browser import Browser, Interrupted
from .daily import LABELS, format_amount


def vault():
    if sys.platform != 'win32':
        raise ValueError('O armazenamento de credenciais está disponível somente no Windows.')
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


class TestDestination:
    def __init__(self, browser):
        self.browser = browser
        self.persisted = None

    def create(self, key, payload):
        self.browser.save_demo()
        self.persisted = (key, payload)
        return key

    def read(self, receipt):
        return self.persisted


class Worker(QObject):
    progress = Signal(int, str)
    done = Signal(str, object)

    def __init__(self, stop, db_path):
        super().__init__()
        self.browser = Browser(stop)
        self.history = History(db_path)
        self.summary = None

    def serve(self, requests):
        try:
            while True:
                action, options = requests.get()
                if action == 'close':
                    break
                self.execute(action, options)
        finally:
            self.browser.close()

    def execute(self, action, options):
        try:
            result = self.run_action(action, options)
        except Interrupted:
            result = {'error': 'Operação interrompida pelo usuário.'}
        except PlaywrightError:
            self.browser.close()
            result = {'error': 'Falha no Chromium, na conexão ou no controle da página. Confira o navegador e o perfil.'}
        except (KeyError, TypeError, OSError):
            result = {'error': 'Configuração, arquivo ou credencial indisponível.'}
        except ValueError as error:
            if isinstance(error, json.JSONDecodeError):
                result = {'error': 'O perfil deve ser um arquivo JSON válido.'}
            else:
                result = {'error': str(error)}
        except Exception:
            result = {'error': 'Erro inesperado ao executar a operação.'}
        if 'error' in result and action in {'start', 'save'}:
            self.summary = None
            self.browser.prepared = None
            try:
                self.history.record('desktop_erro', result)
            except Exception:
                result['error'] += ' O histórico também está indisponível.'
        self.done.emit(action, result)

    def run_action(self, action, options):
        if action == 'credentials':
            vault().set_password('Theodoro.Premier', 'operator', json.dumps(options))
            return {'message': 'Credencial armazenada no Gerenciador de Credenciais do Windows.'}
        if action in {'ifood', 'premier'}:
            path, use_vault = options
            profile = json.loads(Path(path).read_text(encoding='utf-8')) if path else None
            credentials = None
            if action == 'premier' and use_vault:
                if not profile or not profile.get('premier', {}).get('login'):
                    raise ValueError('O login automático requer um perfil local com campos de login verificados.')
                stored = vault().get_password('Theodoro.Premier', 'operator')
                if not stored:
                    raise ValueError('Cadastre a credencial do Premier no aplicativo.')
                credentials = json.loads(stored)
            ready = self.browser.connect(action, profile, credentials)
            return {'ready': ready, 'message': (
                'Sessão verificada.' if ready else
                'Conclua ou confira o login no Chromium. A sessão fica aberta durante o uso do aplicativo.'
            )}
        if action == 'start':
            day, demo, profile = options
            self.summary = None
            summary = self.browser.prepare(day, demo, profile, self.progress.emit)
            self.browser.check()
            self.summary = summary if demo else None
            result = {'summary': asdict(summary), 'pending': demo}
            self.history.record('desktop_previa', result)
            return result
        if action == 'save':
            summary = self.summary
            self.summary = None
            if summary is None:
                raise ValueError('Gere a prévia antes de aprovar.')
            entry = Entry(
                'demo', summary.day, 'resumo-diario', summary.day, summary.day,
                summary.day, json.dumps(asdict(summary), sort_keys=True),
                'Teste local', 'aprovado', summary.net,
            )
            self.browser.check()
            status = self.history.send_to_test_destination(
                entry, TestDestination(self.browser), approved_payload=entry.payload(),
            )
            self.browser.prepared = None
            result = {'status': status, 'summary': asdict(summary)}
            self.history.record('desktop_teste', result)
            return result
        raise ValueError('Operação desconhecida.')


class Window(QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.setWindowTitle('Theodoro | Automação financeira')
        self.resize(780, 565)
        self.history = History(path)
        self.stop = Event()
        self.busy = False
        self.pending = False
        self.profile_path = None
        self.requests = Queue()
        self.worker = Worker(self.stop, path)
        self.worker.progress.connect(self.update_progress, Qt.ConnectionType.QueuedConnection)
        self.worker.done.connect(self.completed, Qt.ConnectionType.QueuedConnection)
        self.thread = Thread(target=self.worker.serve, args=(self.requests,), name='TheodoroBrowser')
        self.thread.start()

        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        operation, history = QWidget(), QWidget()
        tabs.addTab(operation, 'Automação')
        tabs.addTab(history, 'Histórico e erros')
        layout = QVBoxLayout(operation)
        title = QLabel('Automação financeira')
        title.setStyleSheet('font-size: 24px; font-weight: 650')
        layout.addWidget(title)
        connections = QHBoxLayout()
        layout.addLayout(connections)
        self.connection_labels = {}
        self.controls = []
        for portal, name in [('ifood', 'iFood'), ('premier', 'Premier Delivery')]:
            card = QVBoxLayout()
            connections.addLayout(card)
            label = QLabel('Sessão a verificar')
            self.connection_labels[portal] = label
            self.add_button(card, f'Conectar ao {name}', lambda p=portal: self.connect_portal(p))
            card.addWidget(label)

        options = QHBoxLayout()
        layout.addLayout(options)
        options.addWidget(QLabel('Data de referência'))
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('dd/MM/yyyy')
        options.addWidget(self.date)
        self.demo = QCheckBox('Simulação local')
        self.demo.setChecked(True)
        options.addWidget(self.demo)
        self.use_vault = QCheckBox('Usar credencial do Premier')
        options.addWidget(self.use_vault)
        settings = QHBoxLayout()
        layout.addLayout(settings)
        self.add_button(settings, 'Selecionar perfil local', self.select_profile)
        self.add_button(settings, 'Guardar credencial do Premier', self.set_credentials)
        self.profile_label = QLabel('Nenhum perfil selecionado')
        layout.addWidget(self.profile_label)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.add_button(actions, 'Iniciar automação', self.start)
        self.cancel_button = QPushButton('Parar automação')
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_button)
        self.approve = QPushButton('Aprovar e salvar teste')
        self.approve.clicked.connect(self.approve_test)
        actions.addWidget(self.approve)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.message = QLabel('Pronto para iniciar')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        history_layout = QVBoxLayout(history)
        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        history_layout.addWidget(self.history_view)
        self.refresh_history()
        self.update_controls()

    def add_button(self, layout, name, callback):
        button = QPushButton(name)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self.controls.append(button)

    def update_controls(self):
        for button in self.controls:
            button.setEnabled(not self.busy)
        for control in (self.date, self.demo, self.use_vault):
            control.setEnabled(not self.busy)
        self.cancel_button.setEnabled(self.busy or self.pending)
        self.approve.setEnabled(self.pending and not self.busy)

    def dispatch(self, action, options):
        if self.busy:
            return
        self.stop.clear()
        self.busy = True
        self.update_controls()
        self.requests.put((action, options))

    def start(self):
        self.pending = False
        self.preview.clear()
        self.update_progress(5, 'Abrindo Chromium')
        self.dispatch('start', (self.date.date().toString('yyyy-MM-dd'),
                                self.demo.isChecked(), self.profile_path))

    def cancel(self):
        self.stop.set()
        self.pending = False
        self.message.setText('Interrupção solicitada. Aguardando a etapa atual.')
        self.update_controls()

    def connect_portal(self, portal):
        self.message.setText('Abrindo portal autorizado no Chromium')
        self.dispatch(portal, (self.profile_path, self.use_vault.isChecked()))

    def select_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Perfil verificado', '', 'JSON (*.json)')
        if path:
            self.profile_path = path
            self.profile_label.setText(Path(path).name)

    def set_credentials(self):
        if sys.platform != 'win32':
            self.message.setText('A credencial pode ser armazenada somente no Windows.')
            return
        email, ok = QInputDialog.getText(self, 'Credencial do Premier', 'E-mail')
        if not ok or not email.strip():
            return
        password, ok = QInputDialog.getText(self, 'Credencial do Premier', 'Senha',
                                            QLineEdit.EchoMode.Password)
        if ok and password:
            self.dispatch('credentials', (email.strip(), password))

    def approve_test(self):
        approved = QMessageBox.question(self, 'Aprovar teste', 'Salvar a prévia no destino fictício?')
        if approved == QMessageBox.StandardButton.Yes:
            self.pending = False
            self.dispatch('save', None)

    @Slot(int, str)
    def update_progress(self, value, message):
        self.message.setText(message)
        self.progress.setValue(value)

    @Slot(str, object)
    def completed(self, action, result):
        self.busy = False
        if 'error' in result:
            if action in self.connection_labels:
                self.connection_labels[action].setText('Falha ao verificar sessão')
            self.update_progress(0, result['error'])
        elif action == 'start':
            self.pending = result['pending'] and not self.stop.is_set()
            summary = result['summary']
            self.preview.setPlainText(
                f"Data das vendas e dos recebimentos consultados: {summary['day']}\n\n"
                + '\n'.join(f'{label}   R$ {format_amount(summary[key])}' for key, label in LABELS.items())
            )
        elif action == 'save':
            messages = {
                'confirmed': 'Lançamento fictício confirmado.',
                'duplicate': 'O teste desta data já foi confirmado.',
                'review': 'Resultado incerto ou divergente. Revise o histórico.',
            }
            self.update_progress(100, messages[result['status']])
        else:
            if action in self.connection_labels:
                self.connection_labels[action].setText('Conectado' if result['ready'] else 'Sessão a verificar')
            self.message.setText(result['message'])
        self.refresh_history()
        self.update_controls()

    def refresh_history(self):
        try:
            self.history_view.setPlainText(json.dumps(self.history.runs(), ensure_ascii=False, indent=2))
        except Exception:
            self.history_view.setPlainText('Histórico indisponível.')

    def closeEvent(self, event):
        self.stop.set()
        self.requests.put(('close', None))
        self.thread.join()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Theodoro')
    app.setStyle('Fusion')
    data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    old_history = Path('data/history.sqlite')
    db_path = Path(os.environ.get('THEODORO_DB', data / 'history.sqlite'))
    if 'THEODORO_DB' not in os.environ and old_history.is_file() and not db_path.exists():
        import sqlite3
        from contextlib import closing
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(old_history)) as source, closing(sqlite3.connect(db_path)) as target:
            source.backup(target)
    window = Window(db_path)
    window.show()
    return app.exec()
