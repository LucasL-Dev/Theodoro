import csv
import hashlib
import io
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .daily import LABELS

SALES = ('gross', 'fees', 'adjustments', 'net')
COLUMNS = {
    'store': ('Estabelecimento', 'loja', 'id loja', 'merchant id', 'restaurante'),
    'sale_date': ('Data da venda', 'data venda', 'data do pedido'),
    'competence_date': ('Data de competência', 'competência', 'data competência'),
    'receipt_date': ('Data de recebimento', 'data do recebimento', 'data do repasse'),
    'id': ('Identificador do registro', 'id transação', 'id lançamento', 'transaction id'),
    'gross': ('Vendas brutas', 'valor bruto', 'venda bruta'),
    'fees': ('Taxas e comissões', 'taxas', 'comissão', 'valor da taxa'),
    'adjustments': ('Descontos e ajustes', 'ajustes', 'descontos'),
    'net': ('Vendas líquidas', 'valor líquido', 'venda líquida'),
    'payout': ('Repasses recebidos', 'repasse recebido', 'valor recebido'),
}
LIMIT = 100_000


def normalize(value):
    text = unicodedata.normalize('NFKD', str(value)).casefold()
    return ' '.join(re.sub(r'[^a-z0-9 ]', '', ''.join(c for c in text if not unicodedata.combining(c))).split())


def read_file(path, sheet=None, delimiter=None):
    path = Path(path)
    if path.stat().st_size > 35_000_000:
        raise ValueError('O arquivo excede o limite de 35 MB.')
    data = path.read_bytes()
    fingerprint = hashlib.sha256(data).hexdigest()
    try:
        if path.suffix.lower() == '.xlsx':
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            try:
                sheets = book.sheetnames
                rows = materialize(book[sheet or sheets[0]].iter_rows(values_only=True))
            finally:
                book.close()
        elif path.suffix.lower() == '.csv':
            try:
                source = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                source = data.decode('cp1252')
            if delimiter is None:
                try:
                    delimiter = csv.Sniffer().sniff(source[:8192], delimiters=';,\t').delimiter
                except csv.Error:
                    first = next((line for line in source.splitlines() if ';' in line or ',' in line or '\t' in line), '')
                    delimiter = max(';\t,', key=first.count)
            rows = materialize(csv.reader(io.StringIO(source, newline=''), delimiter=delimiter, strict=True))
            sheets = []
        else:
            raise ValueError('Escolha um arquivo CSV ou XLSX.')
    except (BadZipFile, InvalidFileException, UnicodeError, csv.Error, KeyError):
        raise ValueError('Arquivo inválido ou aba indisponível. Confira o formato selecionado.') from None
    return sheets, rows, fingerprint


def materialize(source):
    rows = []
    for row in source:
        if len(rows) == LIMIT or len(row) > 256:
            raise ValueError('O relatório excede 100 mil linhas ou 256 colunas.')
        rows.append(tuple(row))
    if not rows:
        raise ValueError('O relatório está vazio.')
    return rows


def detect_columns(row):
    headers = [normalize(cell) for cell in row]
    result = {}
    for key, names in COLUMNS.items():
        options = {normalize(name) for name in names}
        matches = [index for index, header in enumerate(headers) if header in options]
        if len(matches) == 1:
            result[key] = matches[0]
    return result


def detect_header(rows):
    return max(range(min(25, len(rows))), key=lambda index: len(detect_columns(rows[index])))


def parse_day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if re.fullmatch(r'\d{2}/\d{2}/\d{4}', text):
        return datetime.strptime(text, '%d/%m/%Y').date()
    return date.fromisoformat(text)


def cents(value, decimal_separator):
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        text = str(value).strip()
        if text.startswith('(') and text.endswith(')'):
            text = '-' + text[1:-1].strip().removeprefix('R$').strip()
        else:
            text = text.removeprefix('R$').strip()
        sep = re.escape(decimal_separator)
        group = re.escape('.' if decimal_separator == ',' else ',')
        if not re.fullmatch(rf'[+-]?(?:\d+|\d{{1,3}}(?:{group}\d{{3}})+)(?:{sep}\d{{1,2}})?', text):
            raise ValueError
        number = Decimal(text.replace('.' if decimal_separator == ',' else ',', '').replace(decimal_separator, '.'))
    if not number.is_finite() or abs(number) >= 10 ** 15:
        raise ValueError
    scaled = number * 100
    if scaled != scaled.to_integral_value():
        raise ValueError
    return int(scaled)


def missing(value):
    return value is None or str(value).strip() == ''


def at(row, index):
    return row[index] if index is not None and index < len(row) else None


def summarize(rows, header, mapping, basis, decimal_separator, fee_sign, adjustment_sign, control_row=None):
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Mapeie uma coluna diferente para cada campo.')
    if 'store' not in mapping or not set(mapping).intersection(LABELS):
        raise ValueError('Mapeie o estabelecimento e pelo menos uma coluna de valores.')
    if set(mapping).intersection(SALES) and basis not in mapping:
        raise ValueError('Mapeie a data escolhida para agrupar as vendas.')
    if 'payout' in mapping and 'receipt_date' not in mapping:
        raise ValueError('Mapeie a data de recebimento para apurar repasses.')
    if control_row is None:
        marked = [
            idx for idx, row in enumerate(rows[header + 1:], header + 1)
            if any(normalize(value) in {'total geral', 'totais gerais'} for value in row)
        ]
        if len(marked) > 1:
            raise ValueError('Há vários totais gerais. Indique a linha de controle e revise as demais linhas.')
        control_row = marked[0] if marked else None
    if control_row is not None and not header < control_row < len(rows):
        raise ValueError('A linha de controle deve estar abaixo do cabeçalho.')

    groups = defaultdict(lambda: {'sales': [], 'payouts': []})
    checked = defaultdict(list)
    signatures, identifiers = set(), set()
    errors = []
    signs = {'fees': fee_sign, 'adjustments': adjustment_sign}
    for index, row in enumerate(rows[header + 1:], header + 1):
        if index == control_row or all(missing(value) for value in row):
            continue
        items = {key: at(row, col) for key, col in mapping.items()}
        store = str(items['store']).strip() if not missing(items['store']) else ''
        try:
            values = {
                key: cents(items[key], decimal_separator) * signs.get(key, 1)
                for key in LABELS if key in items and not missing(items[key])
            }
            dates = {key: parse_day(items[key]) for key in ('sale_date', 'competence_date', 'receipt_date')
                     if key in items and not missing(items[key])}
        except (ValueError, InvalidOperation, OverflowError):
            errors.append(f'Linha {index + 1}: data ou valor monetário inválido.')
            continue
        if not store or not values:
            errors.append(f'Linha {index + 1}: estabelecimento ou valores ausentes.')
            continue
        has_sale = bool(set(values).intersection(SALES))
        if (has_sale and basis not in dates) or ('payout' in values and 'receipt_date' not in dates):
            errors.append(f'Linha {index + 1}: data correspondente à movimentação ausente.')
            continue
        if values.get('fees', 0) > 0 or values.get('gross', 0) < 0 or values.get('payout', 0) < 0:
            errors.append(f'Linha {index + 1}: confira os sinais de venda, taxa ou repasse.')
            continue
        if all(key in values for key in SALES) and sum(values[key] for key in SALES[:3]) != values['net']:
            errors.append(f'Linha {index + 1}: vendas líquidas divergem das vendas brutas, taxas e ajustes.')
            continue
        identifier = None if missing(items.get('id')) else (store, str(items['id']).strip())
        signature = (store, tuple(dates.items()), tuple(values.items()))
        if (identifier and identifier in identifiers) or (identifier is None and signature in signatures):
            errors.append(f'Linha {index + 1}: possível duplicidade. Confira o registro e a coluna de ID.')
            continue
        if identifier:
            identifiers.add(identifier)
        signatures.add(signature)
        if has_sale:
            groups[store, dates[basis]]['sales'].append((values, dates))
        if 'payout' in mapping and 'receipt_date' in dates:
            groups[store, dates['receipt_date']]['payouts'].append(values.get('payout'))
        for key, amount in values.items():
            checked[key].append(amount)

    result = []
    for (store, day), group in sorted(groups.items()):
        sales = group['sales']
        totals = {key: sum(values[key] for values, _ in sales) if sales and all(key in values for values, _ in sales)
                  else None for key in SALES}
        if totals['net'] is None and 'net' not in mapping and all(totals[key] is not None for key in SALES[:3]):
            totals['net'] = sum(totals[key] for key in SALES[:3])
        totals['payout'] = sum(group['payouts']) if group['payouts'] and None not in group['payouts'] else None
        summary = {'store': store, 'day': day.isoformat(), **totals}
        for key in ('sale_date', 'competence_date'):
            unique = {dates.get(key) for _, dates in sales}
            summary[key] = next(iter(unique)).isoformat() if len(unique) == 1 and None not in unique else None
        summary['receipt_date'] = day.isoformat() if group['payouts'] else None
        result.append(summary)

    controls = []
    if control_row is not None:
        for key, label in LABELS.items():
            cell = at(rows[control_row], mapping.get(key))
            if missing(cell):
                continue
            try:
                expected = cents(cell, decimal_separator) * signs.get(key, 1)
            except (ValueError, InvalidOperation, OverflowError):
                errors.append(f'Linha de controle: total inválido para {label.lower()}.')
                continue
            if not checked[key] or sum(checked[key]) != expected:
                errors.append(f'Total de controle divergente para {label.lower()}.')
            else:
                controls.append(label)
    return result, errors, controls
