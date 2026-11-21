import csv
import sys
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from financeiro.mapping import load
from financeiro.sync import History


st.set_page_config(page_title='Sincronização financeira')
st.title('Sincronização financeira')
st.info('Modo de simulação. Envie um CSV local para visualizar os lançamentos.')
history = History(ROOT / 'data/history.sqlite')
left, right = st.columns(2)
left.metric('iFood', 'Integração pendente')
right.metric('Premier Delivery', 'Integração pendente')
if st.button('Testar conexões'):
    st.warning('A validação das conexões depende do acesso autorizado aos portais.')

start = st.date_input('Data inicial', date.today().replace(day=1))
end = st.date_input('Data final', date.today())
report = st.file_uploader('Relatório CSV', type=['csv'])
mapping = st.file_uploader('Mapeamento JSON', type=['json'])
use_demo = st.checkbox('Usar dados fictícios do exemplo')

if st.button('Sincronizar agora (simulação)'):
    if not use_demo and (report is None or mapping is None):
        st.error('Envie o CSV e o JSON ou selecione os dados fictícios.')
    else:
        try:
            with tempfile.TemporaryDirectory() as folder:
                if use_demo:
                    report_path = ROOT / 'examples/report.csv'
                    mapping_path = ROOT / 'examples/mapping.json'
                else:
                    report_path = Path(folder) / 'report.csv'
                    mapping_path = Path(folder) / 'mapping.json'
                    report_path.write_bytes(report.getvalue())
                    mapping_path.write_bytes(mapping.getvalue())
                entries, errors = load(report_path, mapping_path, start, end)
                history.simulate(entries, errors)
        except (OSError, ValueError, KeyError, TypeError, csv.Error):
            st.error('Confira o período e os formatos do relatório e do mapeamento.')

runs = history.runs()
if runs:
    latest = runs[0]
    st.caption(f"Última simulação em {latest['utc']} UTC")
    cols = st.columns(3)
    cols[0].metric('Processados', latest['processed'])
    cols[1].metric('Enviados', latest['sent'])
    cols[2].metric('Com erro ou em revisão', len(latest['errors']) + len(latest['review']))
    with st.expander('Visualizar lançamentos'):
        st.dataframe(latest['preview'])
    with st.expander('Relatório de erros'):
        st.json({'linhas': latest['errors'], 'chaves_em_revisao': latest['review']})
    with st.expander('Histórico de sincronizações'):
        st.dataframe([
            {key: run[key] for key in ('run_id', 'utc', 'processed', 'sent', 'duplicates')}
            for run in runs
        ])
