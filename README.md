# Theodoro para Windows

O Theodoro usa PySide6 para a interface, Playwright para operar no Chromium visível e SQLite para o histórico. Na simulação local, o navegador consulta uma tela financeira fictícia, confere as datas, lê os totais, abre outro formulário, preenche os campos e só aciona **Salvar teste** após confirmação no aplicativo. A leitura do recibo confere os valores antes de marcar o lançamento fictício como confirmado.

## Abrir no Windows

Na aba **Actions** do GitHub, abra uma execução bem-sucedida de **Executável Windows** e baixe o artefato **Theodoro-Windows**. Extraia o ZIP inteiro e abra **Theodoro.exe** na pasta extraída. O Chromium acompanha o executável em `_internal/browsers/chromium-*/chrome-win/chrome.exe`. Mantenha a pasta completa. A distribuição é portátil e não assinada.

1. Selecione a data, mantenha **Simulação local** marcada e inicie a automação.
2. Acompanhe a consulta e o preenchimento no Chromium.
3. Confira o resumo no aplicativo. Use **Aprovar e salvar teste** para testar a confirmação ou **Parar automação** para interromper. A interrupção é cooperativa e aguarda o retorno da ação atual do navegador.
4. Consulte **Histórico e erros** para conferir o resultado. A chave de teste por data impede repetir um resultado confirmado ou desconhecido. Para um segundo ensaio bem-sucedido, escolha outra data.

Os valores usam centavos inteiros. A conciliação compara vendas brutas, taxas e ajustes com vendas líquidas. Repasses consultados pelo dia do recebimento ficam separados e não são somados ao saldo das vendas. O perfil precisa identificar de forma inequívoca o dia de cada total. A demonstração usa a mesma data de calendário para os dois filtros.

O histórico fica em `%LOCALAPPDATA%\Theodoro\history.sqlite` no Windows. O aplicativo reaproveita o formato de histórico do commit inicial e, se iniciado da raiz do projeto, importa `data/history.sqlite` na primeira execução. Use `THEODORO_DB` para indicar um caminho específico. A CLI de CSV continua disponível para conferência offline, com `python main.py --help`.

## Diagnóstico e perfil do operador

Os dois portais retornaram HTTP 403 no proxy do ambiente de desenvolvimento. Os fluxos autenticados, os campos reais e a confirmação do Premier ainda precisam ser verificados com uma conta autorizada. A gravação real está desabilitada no aplicativo.

Com Python 3.12 em uma máquina que tenha acesso aos serviços, instale as dependências com `python -m pip install -r requirements.txt` e o navegador com `python -m playwright install chromium`. Abra o aplicativo com `python desktop.py`. Para inspecionar os portais com o seletor visual do Playwright, use:

```powershell
python -m theodoro.diagnose ifood
python -m theodoro.diagnose premier
```

O Chromium abre junto com o Inspector. Conclua o login manualmente e use **Pick locator** para identificar controles. Evite capturas de telas com informações financeiras ou credenciais. Mantenha o perfil preenchido fora do repositório. O Inspector usa uma sessão isolada da sessão do aplicativo.

- Copie `examples/profile.template.json`. Os seletores estão vazios até que sejam verificados por um operador autorizado.
- No iFood, identifique um marcador visível apenas com sessão autenticada (`ready`), a sequência de cliques da área financeira (`open`), os filtros de data, o botão de consulta, as datas retornadas e os cinco totais. O leitor inicial requer inputs que aceitem ISO `AAAA-MM-DD`, datas de resultado no mesmo formato e decimais com vírgula sem agrupamento de milhares. Se o portal usar outros formatos ou controles, adapte o leitor após verificá-los. Verifique a granularidade por loja e se as datas só mudam quando a consulta termina. Use `fee_sign` e `adjustment_sign` com valor -1 quando o portal exibir o sinal inverso ao lançamento contábil.
- No Premier, identifique o marcador autenticado e a sequência até o formulário. Confirme campos, formato e comportamento ao preencher. Para autorizar apenas a prévia no formulário, ajuste `allow_unsaved_fill` para `true` após verificar que digitar e desfocar não gravam dados. Em `fields`, mapeie somente os campos validados. As chaves aceitas são `sale_date`, `receipt_date`, `gross`, `fees`, `adjustments`, `net` e `payout`. A decisão contábil sobre quais valores devem ser lançados exige validação, especialmente vendas líquidas e repasses.
- Para login opcional no Premier, adicione `login` ao objeto `premier` com seletores verificados para `email`, `password` e `submit`. Use **Guardar credencial do Premier** para armazenar os dados no Gerenciador de Credenciais do Windows. A senha fica fora do JSON, do histórico e dos logs.
- Selecione o perfil no aplicativo, clique para conectar aos dois portais e conclua login e verificações adicionais no Chromium. As sessões ficam na memória enquanto o aplicativo estiver aberto. Desmarque a simulação para consultar os portais com o perfil verificado.

Antes de implementar envios, valide gravação em ambiente de teste com aprovação, referência externa única, busca de duplicidade no Premier e releitura dos valores salvos. Confirme o procedimento de reconciliação quando houver resposta desconhecida. Ainda não foram verificados lançamentos reais, execução agendada ou navegação autenticada nas plataformas.

## Compilar e testar

Em Windows com PowerShell 7 e Python 3.12, execute `pwsh -File scripts/build-windows.ps1`. A compilação gera `dist/Theodoro/Theodoro.exe` e seus arquivos de suporte. O GitHub Actions executa o mesmo script, que baixa o Chromium, copia os binários para `dist/Theodoro/_internal/browsers` e testa o próprio `Theodoro.exe` em modo headless com a página local de demonstração. O artefato só é publicado após esse teste passar. Os testes com navegador podem ser executados separadamente após instalar o Chromium, definindo `THEODORO_BROWSER_TEST=1` e rodando `python -m unittest discover -s tests -v`. Em desenvolvimento, `THEODORO_CHROMIUM` pode apontar para um Chromium já instalado.
