from PySide6.QtCore import Qt
from functools import partial
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFileDialog, QGridLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QAbstractItemView,
)

from .daily import LABELS, format_amount
from .reports import COLUMNS, detect_columns, detect_header, read_file, summarize


class ImportTab(QWidget):
    def __init__(self, history, send, connect, refresh_history):
        super().__init__()
        self.history = history
        self.send = send
        self.refresh_history = refresh_history
        self.path = None
        self.rows = []
        self.summaries = []
        self.approved = None
        self.run_id = None
        self.errors = []
        self.busy = False
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)
        self.file_button = self.button(grid, 0, 0, 'Abrir CSV ou XLSX', self.choose_file)
        self.file_label = QLabel('Escolha um relatório financeiro')
        grid.addWidget(self.file_label, 0, 1, 1, 4)
        self.sheet = self.combo(grid, 1, 0, 'Aba Excel')
        self.delimiter = self.combo(grid, 1, 2, 'Separador CSV')
        for name, value in [('Automático', None), ('Ponto e vírgula', ';'), ('Vírgula', ','), ('Tabulação', '\t')]:
            self.delimiter.addItem(name, value)
        self.header = QSpinBox()
        self.control = QSpinBox()
        self.control.setSpecialValueText('Automático')
        for col, label, field in [(0, 'Linha de cabeçalho', self.header), (2, 'Linha de total geral', self.control)]:
            grid.addWidget(QLabel(label), 2, col)
            grid.addWidget(field, 2, col + 1)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.raw = self.table()
        self.totals = self.table()
        self.tabs.addTab(self.raw, 'Prévia do arquivo')
        self.tabs.addTab(self.totals, 'Resumo diário')
        options = QWidget()
        self.tabs.addTab(options, 'Mapeamento')
        fields = QGridLayout(options)
        self.mapping = {}
        for index, (key, names) in enumerate(COLUMNS.items()):
            picker = self.combo(fields, index // 2, (index % 2) * 2, names[0])
            picker.currentIndexChanged.connect(self.invalidate)
            self.mapping[key] = picker
        self.basis = self.combo(fields, 6, 0, 'Agrupar vendas por')
        self.basis.addItem('Data da venda', 'sale_date')
        self.basis.addItem('Data de competência', 'competence_date')
        self.decimal = self.combo(fields, 6, 2, 'Separador decimal')
        self.decimal.addItem('Vírgula', ',')
        self.decimal.addItem('Ponto', '.')
        self.fee_sign = self.combo(fields, 7, 0, 'Taxas')
        self.adjustment_sign = self.combo(fields, 7, 2, 'Descontos e ajustes')
        for widget in (self.fee_sign, self.adjustment_sign):
            widget.addItem('Manter sinal', 1)
            widget.addItem('Inverter sinal', -1)
        self.store = self.combo(grid, 3, 0, 'Estabelecimento')
        self.start = QDateEdit(QDate.currentDate())
        self.end = QDateEdit(QDate.currentDate())
        for col, label, field in [(0, 'De', self.start), (2, 'Até', self.end)]:
            field.setCalendarPopup(True)
            field.setDisplayFormat('dd/MM/yyyy')
            grid.addWidget(QLabel(label), 4, col)
            grid.addWidget(field, 4, col + 1)
        actions = QGridLayout()
        layout.addLayout(actions)
        self.check_button = self.button(actions, 0, 0, 'Conferir valores', self.review)
        self.approve_button = self.button(actions, 0, 1, 'Aprovar resumo selecionado', self.approve)
        self.fill_button = self.button(actions, 0, 2, 'Preencher Premier', partial(self.fill, False))
        self.demo_button = self.button(actions, 0, 3, 'Simular preenchimento', partial(self.fill, True))
        self.button(actions, 1, 0, 'Abrir Premier para login', connect)
        self.status = QLabel('Selecione um arquivo para iniciar.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        self.delimiter.currentIndexChanged.connect(lambda: self.load() if self.path and self.path.suffix.lower() == '.csv' else None)
        self.sheet.currentIndexChanged.connect(lambda: self.load(self.sheet.currentText()) if self.path else None)
        self.header.valueChanged.connect(self.reset_mapping)
        self.totals.itemSelectionChanged.connect(self.clear_approval)
        for widget in (self.control, self.basis, self.decimal, self.fee_sign, self.adjustment_sign):
            signal = widget.valueChanged if isinstance(widget, QSpinBox) else widget.currentIndexChanged
            signal.connect(self.invalidate)
        self.store.currentIndexChanged.connect(self.filter_rows)
        self.start.dateChanged.connect(self.filter_rows)
        self.end.dateChanged.connect(self.filter_rows)
        self.update_buttons()

    def button(self, layout, row, col, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button, row, col)
        return button

    @staticmethod
    def combo(layout, row, col, label):
        layout.addWidget(QLabel(label), row, col)
        widget = QComboBox()
        layout.addWidget(widget, row, col + 1)
        return widget

    @staticmethod
    def table():
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        return table

    @staticmethod
    def populate(table, headings, rows):
        table.clear()
        table.setColumnCount(len(headings))
        table.setHorizontalHeaderLabels(headings)
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(str(value) if value is not None else 'Indisponível'))

    def set_busy(self, busy):
        self.busy = busy
        self.setEnabled(not busy)
        self.update_buttons()

    def update_buttons(self):
        can_approve = bool(self.summaries and not self.errors and self.totals.currentRow() >= 0)
        self.check_button.setEnabled(bool(self.rows))
        self.approve_button.setEnabled(can_approve)
        self.fill_button.setEnabled(self.approved is not None)
        self.demo_button.setEnabled(self.approved is not None)

    def clear_approval(self):
        self.approved = None
        self.update_buttons()

    def invalidate(self, *_):
        self.summaries = []
        self.errors = []
        self.totals.setRowCount(0)
        self.clear_approval()
        self.status.setText('Confira o mapeamento e clique em Conferir valores.')

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Selecione o relatório', '', 'Relatórios (*.csv *.xlsx)')
        if path:
            self.path = Path(path)
            self.load()

    def load(self, sheet=None):
        self.invalidate()
        self.rows = []
        self.raw.setRowCount(0)
        try:
            sheets, self.rows, self.fingerprint = read_file(self.path, sheet, self.delimiter.currentData())
        except ValueError as error:
            self.status.setText(str(error))
            self.update_buttons()
            return
        except (OSError, TypeError, IndexError, OverflowError):
            self.status.setText('Não foi possível abrir o relatório. Confira o arquivo, a aba e o separador.')
            self.update_buttons()
            return
        self.file_label.setText(self.path.name)
        self.sheet.blockSignals(True)
        self.sheet.clear()
        self.sheet.addItems(sheets)
        if sheet:
            self.sheet.setCurrentText(sheet)
        self.sheet.blockSignals(False)
        self.sheet.setEnabled(bool(sheets))
        self.delimiter.setEnabled(not sheets)
        self.header.blockSignals(True)
        self.header.setRange(1, len(self.rows))
        self.header.setValue(detect_header(self.rows) + 1)
        self.header.blockSignals(False)
        self.control.setRange(0, len(self.rows))
        self.control.setValue(0)
        self.reset_mapping()
        self.tabs.setCurrentWidget(self.raw)

    def reset_mapping(self, *_):
        if not self.rows:
            return
        row = self.rows[self.header.value() - 1]
        detected = detect_columns(row)
        headings = [f'{index + 1} · {value or "(sem rótulo)"}' for index, value in enumerate(row)]
        for key, picker in self.mapping.items():
            picker.blockSignals(True)
            picker.clear()
            picker.addItem('Não mapeado', None)
            for index, label in enumerate(headings):
                picker.addItem(label, index)
            if key in detected:
                picker.setCurrentIndex(detected[key] + 1)
            picker.blockSignals(False)
        preview = [(index + 1, *record[:len(headings)]) for index, record in enumerate(self.rows[:30])]
        self.populate(self.raw, ['Linha', *headings], preview)
        self.invalidate()

    def review(self):
        self.invalidate()
        mapping = {key: picker.currentData() for key, picker in self.mapping.items() if picker.currentData() is not None}
        try:
            self.summaries, self.errors, controls = summarize(
                self.rows, self.header.value() - 1, mapping, self.basis.currentData(), self.decimal.currentData(),
                self.fee_sign.currentData(), self.adjustment_sign.currentData(),
                self.control.value() - 1 if self.control.value() else None,
            )
        except ValueError as error:
            self.status.setText(str(error))
            return
        selected_store = self.store.currentText()
        self.store.blockSignals(True)
        self.store.clear()
        self.store.addItem('Todos', None)
        self.store.addItems(sorted({row['store'] for row in self.summaries}))
        self.store.setCurrentIndex(max(0, self.store.findText(selected_store)))
        self.store.blockSignals(False)
        if self.summaries:
            for widget, index in ((self.start, 0), (self.end, -1)):
                widget.blockSignals(True)
                widget.setDate(QDate.fromString(sorted(row['day'] for row in self.summaries)[index], 'yyyy-MM-dd'))
                widget.blockSignals(False)
        self.filter_rows()
        self.tabs.setCurrentWidget(self.totals)
        self.run_id = self.history.record('ifood_importado', {
            'arquivo_sha256': self.fingerprint, 'aba': self.sheet.currentText() or None,
            'periodo': self.period(), 'resumos': self.summaries,
            'conferencia': 'divergente' if self.errors else 'pendente',
            'erros': self.errors, 'controles_conferidos': controls, 'premier': 'pendente',
        })
        self.refresh_history()
        tail = '\n'.join(self.errors[:6])
        if len(self.errors) > 6:
            tail += f'\nMais {len(self.errors) - 6} problema(s) no histórico.'
        comparison = 'Controles conferidos: ' + ', '.join(controls) if controls else 'Sem totais de controle comparáveis.'
        self.status.setText((f'{len(self.errors)} problema(s). Corrija antes de aprovar.\n{tail}'
                             if self.errors else 'Selecione um estabelecimento e dia no resumo para aprovar.')
                            + '\n' + comparison)

    def period(self):
        return [field.date().toString('yyyy-MM-dd') for field in (self.start, self.end)]

    def filter_rows(self, *_):
        if not hasattr(self, 'totals'):
            return
        start, end = self.period()
        store = self.store.currentText() if self.store.currentIndex() > 0 else None
        self.visible_rows = [row for row in self.summaries if (store is None or row['store'] == store)
                             and start <= row['day'] <= end]
        keys = ('store', 'day', 'sale_date', 'competence_date', 'receipt_date')
        self.populate(self.totals, ['Estabelecimento', 'Dia', 'Venda', 'Competência', 'Recebimento', *LABELS.values()], [
            [*(row[key] for key in keys), *(format_amount(row[key]) if row[key] is not None else None for key in LABELS)]
            for row in self.visible_rows
        ])
        self.clear_approval()
        if start > end:
            self.status.setText('A data inicial deve preceder a data final.')
        elif self.summaries and not self.visible_rows:
            self.status.setText('Nenhum resumo para o estabelecimento e período escolhidos.')

    def approve(self):
        index = self.totals.currentRow()
        if self.errors or not 0 <= index < len(self.visible_rows):
            return
        row = self.visible_rows[index]
        prompt = f"Aprovar a prévia do dia {row['day']} para o estabelecimento selecionado?"
        if QMessageBox.question(self, 'Aprovar resumo', prompt) != QMessageBox.StandardButton.Yes:
            return
        self.approved = dict(row)
        self.history.record('ifood_aprovado', {
            'importacao': self.run_id, 'estabelecimento': row['store'], 'periodo': self.period(),
            'resumo': self.approved, 'conferencia': 'aprovado', 'premier': 'pendente',
        })
        self.refresh_history()
        self.update_buttons()
        self.status.setText('Resumo aprovado. Para o Premier real, conecte e faça login manualmente antes de preencher.')

    def fill(self, demo):
        if self.approved is not None:
            self.send(self.run_id, self.approved, demo)
