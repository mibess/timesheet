# Timesheet CCEE 2.2

Aplicação desktop Python para preencher o modelo de timesheet no macOS e no Windows. Requer Python 3.9 ou mais recente. A versão 2.2 usa um banco SQLite local para trabalhar com rapidez e mantém o arquivo `.xlsx` ou `.xlsm` atualizado por sincronização. Não depende de PowerShell, automação COM nem de uma instalação do Microsoft Excel.

## Recursos

- Interface moderna, responsiva e consistente nos dois sistemas.
- Banco SQLite local, leve e embutido no próprio Python.
- Carregamento dos registros por data direto do banco e edição por duplo clique.
- Sincronização em segundo plano, com indicadores animados e sem travar a janela.
- Sincronização automática ao abrir e fechar, além do botão **Sincronizar**.
- Detecção de alterações para evitar regravações desnecessárias da planilha.
- Estado vazio orientativo e bloqueio de ações conflitantes durante operações longas.
- Atalhos para Daily, Planning, Weekly e Chapter.
- Atalho para importar as atividades do último dia existente quando o dia aberto está vazio.
- Acesso rápido ao dia atual e ações de tabela habilitadas somente quando aplicáveis.
- Opção de desfazer remoções/limpezas e acesso ao último backup sem interromper o fluxo.
- Indicador visual da meta diária e do total apontado.
- Menu **Opções > Calcular horas** para somar todos os apontamentos da planilha.
- Menu **Opções > Buscar Atualizações** com download, validação e instalação guiada.
- Validação de datas, horários e campos obrigatórios.
- Gravação atômica para reduzir o risco de arquivo incompleto.
- Backup automático em `backups-timesheet` antes de cada regravação da planilha.
- Preferências e logs salvos na pasta de dados do usuário.
- Não é necessário ter o Excel instalado para usar o aplicativo.

## Abrir no macOS

1. Dê duplo clique em `Abrir Timesheet.app` para iniciar sem uma janela do Terminal.
2. Na primeira execução, o aplicativo cria um ambiente `.venv` e instala o `openpyxl`.
3. Se o macOS bloquear o aplicativo, clique nele com o botão direito, escolha **Abrir** e confirme.

O arquivo `INICIAR_TIMESHEET.command` permanece como alternativa para diagnóstico, pois exibe no Terminal eventuais mensagens de instalação ou execução.

Pelo Terminal, a sequência equivalente é:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_timesheet.py
```

## Abrir no Windows

1. Instale o [Python 3.9 ou mais recente](https://www.python.org/downloads/) e marque **Add Python to PATH** durante a instalação.
2. Dê duplo clique em `Abrir Timesheet.vbs` para iniciar sem uma janela do Prompt de Comando.
3. Na primeira execução, o ambiente e a dependência são preparados automaticamente.

O arquivo `INICIAR_TIMESHEET.cmd` permanece como alternativa para diagnóstico, pois exibe eventuais mensagens de instalação ou execução.

## Usar o aplicativo

1. Selecione a planilha do timesheet. Na primeira execução, uma cópia limpa de `Modelo_Timesheet_CCEE.template.xlsx` é criada automaticamente na pasta de dados do usuário.
2. Escolha a data e clique em **Carregar dia**.
   Use **Hoje** para retornar rapidamente à data atual.
3. Adicione atividades pelo formulário ou pelos atalhos.
4. Dê duplo clique em uma célula da tabela para editar seu conteúdo.
5. Confira o total e clique em **Salvar no banco**. Essa operação é local e rápida.
6. Clique em **Sincronizar** quando quiser atualizar imediatamente a planilha.
   A aplicação também sincroniza ao abrir e ao fechar. Após uma sincronização que altere o arquivo, use **Ver backup** no rodapé caso queira localizar a cópia anterior.
7. Use **Opções > Calcular horas** para ver, em um diálogo, o total acumulado de todas as atividades. Alterações ainda não salvas do dia aberto também entram no cálculo.
8. Use **Opções > Buscar Atualizações** para procurar uma versão nova. Quando houver uma, o aplicativo baixa o pacote do macOS ou do Windows, confere sua integridade, protege os dados pendentes, instala e abre novamente.

Atalhos de teclado: `Ctrl+Enter`/`⌘+Enter` adiciona a atividade, `Ctrl+S`/`⌘+S` salva no banco, `Ctrl+Shift+S`/`⌘+Shift+S` sincroniza, `F5` recarrega o dia e `Delete` remove as linhas selecionadas.

## Como funciona a sincronização

No primeiro uso de cada planilha, todos os apontamentos e listas auxiliares são importados para o banco local. A partir daí, o banco passa a ser a fonte principal dos dados e a navegação entre datas não precisa mais abrir o arquivo Excel.

A sincronização exporta o estado completo do banco para a planilha. Se nada mudou desde a última sincronização, o arquivo não é regravado. Caso a planilha seja alterada fora do aplicativo, a diferença é detectada e, na próxima sincronização, o conteúdo vigente do banco substitui os apontamentos do arquivo; a versão externa anterior fica preservada em backup.

## Banco local, backups e logs

O banco é criado automaticamente em:

- macOS: `~/Library/Application Support/TimesheetCCEE/timesheet.sqlite3`
- Windows: `%APPDATA%\TimesheetCCEE\timesheet.sqlite3`

Cada sincronização que regrava a planilha cria uma cópia com data e hora ao lado dela, dentro de `backups-timesheet`.

Os logs ficam em:

- macOS: `~/Library/Application Support/TimesheetCCEE/timesheet.log`
- Windows: `%APPDATA%\TimesheetCCEE\timesheet.log`

## Configuração

Edite `settings.json` para alterar atividade, ticket, observação, meta diária e atalhos padrão. Todo o sistema usa exclusivamente Python.

## Publicar atualizações

O projeto está preparado para usar **GitHub Releases**, que funciona como o servidor de atualizações. O workflow `.github/workflows/release.yml` testa o aplicativo, cria um ZIP específico para macOS e outro para Windows, calcula o SHA-256 de ambos, gera o `update.json` e publica os três arquivos no release.

O repositório e seus releases precisam ser públicos para o aplicativo baixar os arquivos sem credenciais. Caso o código não possa ser público, use um repositório público separado apenas para os pacotes ou hospede os três arquivos em um servidor HTTPS/S3/R2 e aponte `update-config.json` para o manifesto.

### Primeira publicação no GitHub

1. Crie um repositório no GitHub, envie este projeto e habilite o GitHub Actions.
2. Confirme que a versão em `timesheet_ccee/__init__.py` está correta.
3. Crie e envie uma tag com a mesma versão:

```bash
git tag v2.2.0
git push origin v2.2.0
```

4. Aguarde o workflow **Publicar atualização** terminar.
5. Distribua os arquivos `Timesheet-CCEE-macOS.zip` e `Timesheet-CCEE-Windows.zip` da página **Releases**. Esses pacotes já recebem automaticamente o endereço correto do repositório.

O `update-config.json` existente na raiz aponta para este repositório. Nos ZIPs criados pelo workflow, o endereço é confirmado automaticamente a partir do repositório que executou a publicação.

### Publicações seguintes

1. Atualize `__version__` em `timesheet_ccee/__init__.py`, por exemplo para `2.3.0`.
2. Faça commit e push das alterações.
3. Crie e envie a tag correspondente (`v2.3.0`).

O endereço estável `releases/latest/download/update.json` passa a apontar para o novo manifesto. As instalações existentes encontram a versão nova em **Buscar Atualizações**. O GitHub oferece oficialmente URLs estáveis no formato `releases/latest/download/nome-do-arquivo` para assets do release mais recente.

### Segurança e preservação dos dados

- O manifesto e os pacotes só são aceitos por HTTPS.
- Cada download é comparado ao SHA-256 publicado no manifesto e o ZIP é validado antes da instalação.
- Pacotes com caminhos inseguros, links simbólicos, aplicativo diferente ou versão divergente são recusados.
- `settings.json`, `Modelo_Timesheet_CCEE.xlsx`, `.venv` e `backups-timesheet` existentes não são substituídos.
- O arquivo versionado `Modelo_Timesheet_CCEE.template.xlsx` não contém apontamentos nem autoria pessoal; ele serve apenas para criar novas planilhas de trabalho.
- O banco SQLite e os logs ficam fora da pasta do aplicativo e não são afetados.
- Antes da troca dos arquivos, alterações abertas são salvas no banco e a planilha é sincronizada.
- Os arquivos anteriores são copiados para a pasta de dados do usuário, dentro de `updates`, permitindo diagnóstico e recuperação em caso de falha.

Para uma distribuição corporativa, também é recomendável assinar o aplicativo/ZIP com certificado de desenvolvedor: **Developer ID + notarização** no macOS e **Authenticode** no Windows. Isso evita alertas do Gatekeeper e do SmartScreen; é uma etapa separada do mecanismo de atualização.
