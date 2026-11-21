import argparse
import csv
import json
import logging
from datetime import date

from financeiro.mapping import load
from financeiro.sync import History


def main():
    parser = argparse.ArgumentParser(description='Simulação financeira iFood → Premier Delivery')
    parser.add_argument('--report', required=True)
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--start', required=True, type=date.fromisoformat)
    parser.add_argument('--end', required=True, type=date.fromisoformat)
    parser.add_argument('--db', default='data/history.sqlite')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        entries, errors = load(args.report, args.mapping, args.start, args.end)
        report = History(args.db).simulate(entries, errors)
    except (OSError, ValueError, KeyError, csv.Error):
        logging.error('Falha ao ler o relatório ou o mapeamento. Confira os formatos e permissões.')
        return 2
    logging.info('Simulação %s concluída com %s registros analisados', report['run_id'], report['processed'])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report['errors'] or report['review'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
