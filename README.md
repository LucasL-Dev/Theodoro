# Automação financeira iFood → Premier Delivery

O fluxo local importa CSV, valida e classifica movimentações, gera uma prévia e registra cada simulação em SQLite. A interface e a CLI executam apenas simulações.

## Diagnóstico técnico

Na investigação inicial, o proxy retornou HTTP 403 ao estabelecer o túnel para `inside.premierdelivery.com.br`, `developer.ifood.com.br` e `portal.ifood.com.br`. A requisição não chegou aos portais. Os fluxos autenticados e a disponibilidade de uma API financeira ou de um relatório exportável para esta conta continuam por verificar. O CSV e as categorias em `examples/` são fictícios.

Quando houver acesso autorizado:

1. Consultar a documentação oficial do iFood e verificar quais relatórios ou recursos financeiros a conta pode acessar. Preferir a integração oficial ou exportação disponível. Registrar filtros, campos, identificadores, granularidade, moeda e formatos com uma amostra autorizada.
2. Entrar no Premier Delivery e verificar a navegação até Financeiro, os campos obrigatórios, as datas, o tratamento de sinais, as categorias, a referência externa e a confirmação de salvamento. Se o portal solicitar MFA ou CAPTCHA, concluir a etapa manualmente.
3. Conferir com a pessoa responsável quais linhas representam vendas, encargos e dinheiro recebido. Verificar se o identificador da origem é estável por loja e tipo antes de aplicar o mapeamento real. Validar a prevenção de duplicidade contra o histórico do próprio portal, incluindo lançamentos manuais.
4. Aprovar um lote em ambiente de teste, registrar os lançamentos e conferir os campos persistidos. Em caso de falha após iniciar uma gravação, reconciliar o resultado antes de qualquer nova tentativa. Habilitar produção ou agendamento somente após essa validação.

## Executar localmente

Requer Python 3.12 ou superior. A CLI e os testes usam a biblioteca padrão.

```sh
python main.py --report examples/report.csv --mapping examples/mapping.json \
  --start 2026-11-01 --end 2026-11-30
python -m unittest discover -s tests -v
```

Para abrir o painel:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run dashboard/app.py --server.address 127.0.0.1
```

Selecione novembro de 2026 no painel, marque **Usar dados fictícios do exemplo** e execute a simulação. Para um CSV local, carregue também o JSON que mapeia os seus cabeçalhos e categorias. O filtro usa a data de competência configurada como `reference_date`. A data da venda e a data do repasse são preservadas separadamente. Os valores são inteiros em centavos. Os relatórios apresentam as movimentações individualmente para evitar somar vendas e repasses como se fossem receitas distintas. Na CLI, o código de saída é 0 para simulações sem erros ou registros em revisão, 1 quando há linhas inválidas ou pendências e 2 quando a entrada não pode ser processada.

O histórico fica em `data/history.sqlite` e guarda a prévia financeira. Restrinja o acesso ao arquivo e aos relatórios de origem. Use `.env.example` como referência para as futuras integrações autenticadas. A simulação não usa credenciais.

O envio e a releitura do lançamento foram exercitados com um destino fictício isolado pelos testes. A chave local combina loja, identificador e tipo de movimentação. Um resultado desconhecido bloqueia novas tentativas com a mesma chave e vai para revisão. A coleta autenticada, a conferência no Premier, os envios reais e a rotina diária dependem das verificações acima.
