# Theodoro para Windows

O Theodoro usa PySide6 para a interface, Playwright para operar no Chromium visível e SQLite para o histórico. Na simulação local, o navegador consulta uma tela financeira fictícia, confere as datas, lê os totais, abre outro formulário, preenche os campos e só aciona **Salvar teste** após confirmação no aplicativo. A leitura do recibo confere os valores antes de marcar o lançamento fictício como confirmado.

## Abrir no Windows

Na aba **Actions** do GitHub, abra uma execução bem-sucedida de **Executável Windows** e baixe o artefato **Theodoro-Windows**. Extraia o ZIP inteiro e abra **Theodoro.exe** na pasta extraída. O Chromium acompanha o executável em `_internal/browsers/chromium-*/chrome-win/chrome.exe`. Mantenha a pasta completa. A distribuição é portátil e não assinada.

1. Selecione a data, clique em **Iniciar simulação**.
2. Acompanhe a consulta e o preenchimento no Chromium.
3. Confira o resumo no aplicativo. Use **Aprovar e salvar teste** para testar a confirmação ou **Parar automação** para interromper. A interrupção é cooperativa e aguarda o retorno da ação atual do navegador.
4. Consulte **Histórico e erros** para conferir o resultado. A chave de teste por data impede repetir um resultado confirmado ou desconhecido. Para um segundo ensaio bem-sucedido, escolha outra data.

Os valores usam centavos inteiros. A conciliação compara vendas brutas, taxas e ajustes com vendas líquidas. Repasses consultados pelo dia do recebimento ficam separados e não são somados ao saldo das vendas. O perfil precisa identificar de forma inequívoca o dia de cada total. A demonstração usa a mesma data de calendário para os dois filtros.

O histórico fica em `%LOCALAPPDATA%\Theodoro\history.sqlite` no Windows. O aplicativo reaproveita o formato de histórico do commit inicial e, se iniciado da raiz do projeto, importa `data/history.sqlite` na primeira execução. Use `THEODORO_DB` para indicar um caminho específico. A CLI de CSV continua disponível para conferência offline, com `python main.py --help`.

## Configurar automação no Windows

Use a aba **Configurar automação** no próprio executável. O login é manual e as sessões ficam no Chromium até fechar o aplicativo. CAPTCHA e MFA são concluídos pelo operador. Os perfis ficam na pasta do histórico, normalmente `%LOCALAPPDATA%\Theodoro`, nos arquivos `automation.json` e `automation-demo.json`. A captura salva seletores estruturais únicos, sem texto da página, valores de campos, URLs da sessão ou credenciais. O estabelecimento fica representado por um resumo criptográfico do rótulo selecionado.

1. Selecione o portal e clique em **Abrir portal**. Conclua o login e volte à tela inicial autenticada de onde a operação normal começa.
2. Selecione **Marcador da tela inicial autenticada** e clique em **Capturar controle**. Clique no elemento no Chromium. Para ensinar um menu, selecione **Adicionar clique de navegação**, capture o botão ou link e depois clique nele novamente no navegador para avançar. A captura em si não executa o clique. Repita na ordem em que serão usados.
3. Selecione uma etapa existente para testar sua presença na página atual ou substituí-la com **Capturar controle**. **Remover seleção** exclui a etapa selecionada. Se o fluxo parar, a mensagem indica o portal e a etapa a revisar. Alterações são salvas à medida que você configura.
4. Para ensaiar a configuração com páginas de demonstração, marque **Usar páginas fictícias**, configure os dois portais e clique em **Reproduzir páginas fictícias**. O perfil fictício fica separado do real.

### iFood

- Ensine os menus até Financeiro. Selecione a loja no portal e capture o controle que exibe o estabelecimento ativo. Prefira um rótulo que identifique uma única loja. O teste real compara a loja antes e depois da consulta.
- Capture os filtros de data de vendas e de recebimentos e o botão **Consultar**. Defina o formato para filtros de texto na opção **Data digitada**. Se um filtro governa ambos os períodos, confirme isso no portal antes de associá-lo às duas etapas.
- Faça uma consulta manual. Capture as duas datas **no resultado da consulta**, não nos filtros. Defina o formato em **Data no resultado**. Capture individualmente os cinco totais exibidos. O leitor aceita valores decimais brasileiros, agrupamento por milhares e o prefixo R$. Valide a convenção dos sinais de taxas e ajustes antes do primeiro teste. O conciliador exige que vendas brutas, taxas e ajustes resultem em vendas líquidas. Repasses efetivamente recebidos ficam separados.
- Use controles únicos no documento principal. Seletores dos controles de iframes, calendários que exigem uma sequência interativa e formatos financeiros diferentes exigem adaptação após inspeção do portal.

### Premier Delivery

- Capture os menus de navegação, o formulário e os campos data/valor que correspondem ao resumo. Capture os campos dentro do formulário, com o rótulo correto. Preencha manualmente quaisquer campos obrigatórios não financeiros que não venham do iFood.
- Confirme no portal que digitar e sair do campo não grava nenhuma alteração. Só então marque a confirmação na aba de configuração. O teste bloqueia requisições HTTP de alteração e mensagens WebSocket de saída na aba de prévia do Premier. Se o portal depender desse tráfego para carregar a tela, a etapa pode falhar. Feche a aba do Premier para iniciar outra sessão de configuração fora do modo de prévia.
- Antes de clicar em **Testar integração real**, volte nos dois portais às telas de início usadas ao ensinar o percurso. Deixe o estabelecimento correto selecionado. Escolha a data na aba **Automação**. O aplicativo lê os totais, preenche e confere o formulário e apresenta a prévia. O botão de salvar é exclusivo da simulação original.

O proxy do ambiente de desenvolvimento retornou HTTP 403 para ambos os portais. A configuração assistida foi exercitada com páginas fictícias. Os controles reais devem ser identificados e validados com a conta autorizada no Windows.

## Compilar e testar

Em Windows com PowerShell 7 e Python 3.12, execute `pwsh -File scripts/build-windows.ps1`. A compilação gera `dist/Theodoro/Theodoro.exe` e seus arquivos de suporte. O GitHub Actions executa o mesmo script, que baixa o Chromium, copia os binários para `dist/Theodoro/_internal/browsers` e testa o próprio `Theodoro.exe` em modo headless com a página local de demonstração. O artefato só é publicado após esse teste passar. Os testes com navegador podem ser executados separadamente após instalar o Chromium, definindo `THEODORO_BROWSER_TEST=1` e rodando `python -m unittest discover -s tests -v`. Em desenvolvimento, `THEODORO_CHROMIUM` pode apontar para um Chromium já instalado.
