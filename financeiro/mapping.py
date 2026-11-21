import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    account: str
    transaction_id: str
    kind: str
    reference_date: str
    sale_date: str | None
    payout_date: str | None
    description: str
    category: str
    status: str
    amount_cents: int

    @property
    def key(self):
        identity = [self.account, self.transaction_id, self.kind]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def payload(self):
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def money(value, decimal_separator):
    if decimal_separator not in {'.', ','}:
        raise ValueError('Separador decimal inválido')
    separator = re.escape(decimal_separator)
    if not re.fullmatch(rf'[+-]?[0-9]{{1,14}}(?:{separator}[0-9]{{1,2}})?', value):
        raise ValueError('Valor monetário inválido')
    cents = int(Decimal(value.replace(decimal_separator, '.')) * 100)
    if not cents:
        raise ValueError('Valor monetário igual a zero')
    return cents


def load(report, mapping, start: date, end: date):
    if start > end:
        raise ValueError('A data inicial deve preceder ou coincidir com a final')
    config = json.loads(Path(mapping).read_text(encoding='utf-8'))
    columns = config['columns']
    required = {'account', 'transaction_id', 'kind', 'reference_date',
                'description', 'status', 'amount'}
    if not required.issubset(columns):
        raise ValueError('Mapeamento incompleto')
    entries, errors = [], []
    with Path(report).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter=config['delimiter'], strict=True)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not set(columns.values()).issubset(headers):
            raise ValueError('Colunas do relatório incompatíveis com o mapeamento')
        for row in reader:
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Linha com quantidade incorreta de colunas')
                values = {field: row[column].strip() for field, column in columns.items()}
                if any(not values[field] for field in required):
                    raise ValueError('Campo obrigatório ausente')
                reference = datetime.strptime(values['reference_date'], config['date_format']).date()
                if not start <= reference <= end:
                    continue
                kind = values['kind']
                if kind not in config['categories']:
                    raise ValueError('Tipo de movimentação sem categoria')
                dates = {}
                for field in ('sale_date', 'payout_date'):
                    value = values.get(field)
                    dates[field] = (
                        datetime.strptime(value, config['date_format']).date().isoformat()
                        if value else None
                    )
                cents = money(values['amount'], config['decimal_separator'])
                entries.append(Entry(
                    values['account'], values['transaction_id'], kind, reference.isoformat(),
                    dates['sale_date'], dates['payout_date'], values['description'],
                    config['categories'][kind], values['status'], cents,
                ))
            except ValueError:
                errors.append({'line': reader.line_num, 'reason': 'Registro inválido. Confira campos, tipo, datas e valor.'})
    return entries, errors
