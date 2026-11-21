from dataclasses import dataclass

from financeiro.mapping import money


LABELS = {
    'gross': 'Vendas brutas',
    'fees': 'Taxas',
    'adjustments': 'Descontos e ajustes',
    'net': 'Vendas líquidas',
    'payout': 'Repasses recebidos',
}


@dataclass(frozen=True)
class DailySummary:
    day: str
    gross: int
    fees: int
    adjustments: int
    net: int
    payout: int

    @classmethod
    def parse(cls, day, values, fee_sign=1, adjustment_sign=1):
        if any(type(sign) is not int or sign not in (-1, 1) for sign in (fee_sign, adjustment_sign)):
            raise ValueError('As convenções de sinal devem ser 1 ou -1.')
        cents = {
            field: 0 if value in {'0', '0,0', '0,00'} else money(value, ',')
            for field, value in values.items()
        }
        cents['fees'] *= fee_sign
        cents['adjustments'] *= adjustment_sign
        result = cls(day, **cents)
        if (result.gross < 0 or result.fees > 0 or result.payout < 0
                or result.gross + result.fees + result.adjustments != result.net):
            raise ValueError('Os totais não conciliam. Confira os sinais, ajustes e o valor líquido.')
        return result


def format_amount(cents):
    sign = '-' if cents < 0 else ''
    absolute = abs(cents)
    return f'{sign}{absolute // 100},{absolute % 100:02d}'
