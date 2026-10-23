# CAIO 2.0.0.dev10 — referência técnica

## Operação, desempenho e persistência — dev10

A avaliação numerada de todos os 60 itens, os limites e a homologação Windows ficam em `VALIDACAO.md`. `README.md` descreve os fluxos do usuário. Tema e extratores são invariantes; runtime é o conjunto Windows verificado da dev8, sem novas dependências. A revisão altera aplicação/orquestração, persistência e apresentação; não altera os cinco extratores.

- `config.py`: cache limitado de 64 configurações, assinatura de arquivo e cópias independentes; revisão SHA-256 em memória, fora do JSON. `save` valida, obtém `state/config-commit.lock`, compara a revisão e grava atomicamente. Edição concorrente falha antes de sobrescrever. O editor de rotina conserva a revisão da abertura. Escritores de GUI/monitor/manutenção mantêm seus locks de nível superior.
- `store.py`: índices por rotina/data, estado/data, eventos/execução e notificações. Migração aditiva de `runs.checkpoint_at`; consulta de decisão limitada ao período solicitado, último sucesso e maior ocorrência não manual. As tabelas/chaves únicas de períodos e ocorrências continuam sendo a barreira durável contra duplicações. Última execução/publicação é por rotina; tela usa `history_page` com total e filtros, tamanho máximo 200 na API, 25/50/100 na UI. Exportação não herda a paginação.
- `schedule.py`: `day_times` usa chaves de segunda=0 a domingo=6, lista HH:MM; vazio no formulário remove a sobrescrita e usa `times`. `excluded_dates` e calendário nomeado são explícitos. `paused_until` exige ISO com fuso e afeta automação, preservando o contrato de execução manual. Sucesso diário/semanal prevalece sobre oportunidades adicionais. Recuperação escolhe a oportunidade mais recente; não executa o backlog inteiro. Prévia semanal é uma projeção de oportunidades usando o estado atual, sem inventar sucessos futuros.
- `engine.py`: simulação antecipada somente leitura, topologia e dependências condicionais. Posição é a do conjunto selecionado; horário real depende de conclusão anterior. Exceção `queue_delay_seconds` por rotina mantém intervalo global padrão 30 s, aplicado ao lote automático. Aviso de estagnação usa checkpoint/etapa e prazo da rotina; nunca mata processo por falta de log. Timeout já existente é independente.
- `agent.py`/`monitor_status.py`: monitor importa somente tarefas Qt compartilhadas, não `gui.py`. Observação SQLite/planejamento ocorre em Task. Heartbeat atômico registra PID+nascimento, data UTC, estado e intervalo. Leitura confere identidade e prazo `max(15, 2×intervalo+10)`; PID reutilizado não comprova atividade. Sondagem adaptativa 1–30 s; pausa/repouso 30 s, erros 10 s. Agendador é verificado pela GUI no máximo uma vez por minuto; erro é estado desconhecido, não ausente. Não é serviço Windows nem garantia de tempo real.
- `observation.py`/`qt_tasks.py`: uma coleta de fundo por janela, com descarte de resultados de configuração anterior; atualização sobreposta vira uma pendência, não uma fila ilimitada. LogTail lê até 64 KiB por ciclo, mantém decoder UTF-8 e reconhece rotação/truncamento; UI limita a visualização a 800 blocos sem alterar arquivo de log. Controle de acompanhamento preserva a rolagem. Histórico usa QAbstractTableModel e atualizações por linha; tabelas pequenas usam `set_cell`, que só aplica diferenças. Backup/snapshot/prévia/consulta VPN e controles do processo saem da thread gráfica. Configuração e preferências pequenas continuam commits síncronos.
- `editors.py`/`gui.py`: formulários comuns, dependências, tentativas e calendário; advanced JSON continua disponível. E-mail é validado junto ao campo. Outros erros mantêm formulário e mensagem persistente. Guardas de edição e revisão de origem impedem descarte/sobrescrita silenciosos. Preferências da janela são locais em `state/window-preferences.json`; texto livre de busca do histórico não é salvo.
- `script_versions.py`: snapshots novos identificam inventário, entrada, contrato e notas por hash composto, além de nome de versão. Compatibilidade com snapshots antigos de `script.py`. Restauração verifica inventário/metadados e cria `extras/active/<id>/<uuid>`, preservando fonte externa. Importação de pastas tem limites de 2.000 arquivos/100 MB e recusa links; exclui ambientes, perfis/caches e extensões sensíveis conhecidas. `check_dependencies` usa AST e procura módulos no intérprete ativo, sem executar o script; imports dinâmicos/nativos ainda exigem ensaio no alvo. Lixeira restaura desabilitado e revalida conflitos/dependências.
- `operations.py`/`files.py`: prévias de publicação/restauração com hashes, reconferidas antes de aplicar. Eventos rejeita divergência sob a mesma chave e mantém o destino, registrando até 100 exemplos e total. Download gerenciado inválido é copiado/verificado para `rejected/<uuid>` com motivo e execução. Limpeza exige revisão, locks, confinamento e reconferência; só remove logs próprios/temporários gerenciados antigos. Reporta sincronização externa como não verificada. Exportação de rotina mostra inventário/exclusões e bloqueia possíveis segredos; heurística não substitui revisão humana.
- `notifications.py`: ocorrência é persistida mesmo quando silenciada (`delivered=2`), mantendo vínculo exato com execução. Repetições idênticas da mesma execução incrementam contador/última data, evitando uma linha a cada sondagem; execuções distintas não são agrupadas na mesma referência. Preferências por tipo, intervalo de repetição, limite/hora e silêncio local inclusive cruzando meia-noite. Próximo aviso elegível resume ocorrências agrupadas; central mostra 200 registros recentes. Cliques abrem a central, evitando assumir que o balão pertence ao último aviso enviado.
- `exporting.py`: XLSX com abas Execuções/Eventos; texto acima do limite de célula tem referência e partes numeradas na aba Conteúdo longo, com reconstrução testada inclusive caracteres não BMP. Fórmulas são gravadas como string; controles inválidos são escapados. Limite de linhas recusa a exportação em vez de truncar. JSON mantém a estrutura original completa. Sanitização é anterior à escrita; conteúdo exportado é a versão sanitizada.
- `dev_gui.py`: observação real de CPU por delta user+system/tempo de parede; primeira amostra indisponível. RSS e processos próprios usam PID+nascimento; fila ativa, checkpoint, locks e monitor consultáveis. Não estima carga de processos externos nem inventa sincronização de nuvem.

## Instalação e recuperação — dev10

`WindowsTasks.preflight` cria tarefa UUID desabilitada, sem gatilhos e sem execução, usa `TASK_CREATE` para nunca sobrescrever, compara com o mesmo núcleo semântico e remove somente se URI/Author próprios permanecerem. Roda antes do snapshot/cópia de runtime quando o monitor está habilitado. `state/scheduler-preflight.json` registra registro/consulta/remoção. Falha bloqueia a cópia; tarefa não removida é informada pelo nome.

`NativeInstaller._restore` verifica a integridade do snapshot antes de restaurar e registra configuração, banco, scripts/iniciadores, versão, tarefa e atalhos em `state/recovery-report.json`. Componentes independentes são tentados após uma falha; recuperação parcial mantém journal de erro e descreve intervenção. Reportar conclusão não elimina a necessidade do teste Windows real.

## Verificação e ferramentas de lançamento

Use os comandos de teste de `premium-ui.json`, saúde offline, PowerShell portável e `tools/capture_ui.py`. Benchmark: `QT_QPA_PLATFORM=offscreen .venv/bin/python tools/benchmark_gui.py --output docs/evidencias/dev10-benchmark-linux.json`. Abertura inclui importar/construir/mostrar e concluir a primeira observação; CPU é tempo de processo durante 5 s de event loop; QTimer de 10 ms mede latência do loop, não é um teste completo de todas as interações. Amostra única com cache do SO não limpo, identificada por versão/plataforma.

O ZIP inclui `diagnostics/validate_windows_release.ps1` e ferramentas sob `payload/src/release_tools`. O roteiro exige opt-in e runtime privado, usa dados/atalhos temporários e tarefa própria, executa instalação/atualização/reparo/cancelamento/rollback e marcador agendado reais. Não executado neste host. Validação visual/VM sem Python global são etapas manuais documentadas na matriz. Ferramenta de benchmark também acompanha o pacote para ensaio no Windows.

Build: `.venv/bin/python tools/build_native_zip.py --runtime build/restored-dev8/CAIO_2.0.0.dev8/payload/runtime --output build/release-dev10`. Depois verifique com `tools/verify_native_artifact.py`. Não declare versão homologada sem anexar evidências Windows. Snapshot novo em `Versionamento_interno/2.0.0.dev10-caio`; preserve os anteriores.

## Referência histórica — UI dev9

O JSON integral em `assets/dashboard-theme.json` permanece inalterado. `DESIGN.md` registra a intenção e o mapa de tokens; `UX-CONTRACT.md` define os donos dos controles e o comportamento entre páginas. `ui.py` adapta o tema para Qt; `Native.Common.ps1` aplica o mesmo JSON ao instalador e editor WinForms. A navegação lateral mantém os seis painéis existentes e seu estado; `FlowLayout` evita que linhas de ações alarguem a janela. Configurações e manutenção têm rolagem, sem esconder o painel de atividade.

A inicialização do tema é idempotente: abrir uma nova janela não substitui o estilo global existente. O layout de ações libera seus itens antes da destruição Qt; o ciclo de vida foi verificado na suíte completa, além dos testes isolados.

A versão usa o mesmo runtime verificado da dev8 e não acrescenta dependências. Frequências, extratores, autenticação, registro de tarefas, rollback e publicação de relatórios não mudaram. Capturas Qt em 980 × 720, 1040 × 850 e 1440 × 940, com PT/EN/ES, ficam em `evidencias/dev9-visual`. Não comprovam WinForms, DPI, Agendador ou leitor de tela Windows.

## Registro e verificação da tarefa — dev8

Base: fontes dev7 SHA-256 `91db567699a14352ff0ad3ed65e60ea294386bd93c1f9be6524780fb5f122c8d`, produto dev7 `f3cf870b7885b09bd2c31784475e0fdbe7ea928b3ecf8ffffa1084be29b12466`. Os 164 arquivos do snapshot foram conferidos antes das alterações; cinco extratores, runtime, tema e scripts nativos estão preservados. Versionamento interno, sem Git.

O erro enviado ocorreu depois do registro, durante o pós-teste. A dev7 comparava texto de campos XML sem reconhecer padrões omitidos (`Enabled=true`), booleanos XML `1/0`, durações equivalentes (`PT1M`/`PT60S`, `P1D`/`PT24H`) ou caminhos Windows equivalentes. Também comparava todo o XML para decidir registrar novamente, embora o Agendador possa acrescentar metadados. O teste anterior salvava de volta o próprio XML solicitado, deixando esse caso sem cobertura.

Foi reproduzida **a mesma mensagem**, com XML sintético equivalente segundo o esquema; o código dev7 rejeitou-o. Isso é evidência do defeito do verificador, não uma captura do XML do computador do usuário. O log recebido não permite afirmar qual campo específico provocou aquela instalação. A dev8 passa a registrar essa evidência antes do rollback.

- `compare_tasks` é usado na pré-conferência, pós-conferência, manutenção e interface. Aplica somente os padrões documentados e normalizações específicas dos campos. Exemplo importante: ausência de `ExecutionTimeLimit` significa `PT72H`, não o `PT0S` ilimitado solicitado; portanto continua sendo divergência. Argumentos permanecem estritos. Datas com fuso são convertidas à hora local. Caminhos usam regras Windows independentemente do host de teste.
- A conferência abrange 20 campos e as quantidades de ações, gatilhos e usuários de execução. Mantém sessão interativa, privilégios mínimos, comando/argumentos/diretório, repetições e condições de disponibilidade. Ações/gatilhos extras também são rejeitados. Não se remove a verificação para permitir a instalação.
- Tarefas próprias passam a ser registradas por `Schedule.Service.NewTask` / `RegisterTaskDefinition`, com flags criar/atualizar `6`, XML integral e tipo de logon explícito obtido do principal (`InteractiveToken=3` para o monitor). Senha não é solicitada nem armazenada; não se eleva privilégio. O registro de uma tarefa nomeada do legado mantém a rota anterior para compatibilidade de restauração. Consultas COM e liberação do COM continuam compartilhadas.
- Uma definição já equivalente não é registrada outra vez. O teste verifica uma única chamada de registro em duas instalações consecutivas, mesmo com XML normalizado na leitura.
- O pós-teste grava `state/task-registration-check.json`, com data UTC, tarefa, XML esperado/efetivo e resultado por campo. É diagnóstico local da instalação, com caminhos e identificação local; não contém credenciais de login. A reversão não o remove. O erro mostra valores divergentes e o caminho do arquivo. A tabela Qt usa o mesmo resultado, incluindo defaults, evitando marcar como erro uma representação equivalente.
- O log agora identifica **Registrando e conferindo a tarefa do monitor na sessão do usuário**, separado da criação dos atalhos. Falha real continua provocando rollback e não é convertida em sucesso.

Referências primárias: [esquema do Agendador](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema), [RegisterTaskDefinition](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertaskdefinition), [contexto de segurança e privilégios padrão](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks). O comparador não prova que login, VPN ou extração funcionarão; a saúde da atualização permanece offline.

### Teste opcional do Agendador real

`desktop_tests/test_tasks_windows.py::test_real_windows_scheduler_register_read_run_and_remove` exige Windows e a variável de ambiente de desenvolvimento `CAIO_TEST_WINDOWS_SCHEDULER=1`. Registra uma tarefa com identificador exclusivo em diretório temporário, confere o XML, solicita execução de um VBS que grava apenas um marcador local e remove a tarefa no final. Usa WScript oculto, sem extração, navegador ou dados corporativos. O opt-in autoriza somente essa tarefa de teste. É verificação técnica, não passo manual do usuário final.

Neste host Linux, esse teste fica **não executado/skipped**. Não foi executado Agendador real, COM real ou WinForms real nesta revisão. O teste de instalação transacional usa o núcleo real com registro/atalhos/runtime substituídos por fixtures e induz uma mudança para S4U: rejeita-a, restaura o estado anterior e conserva o diagnóstico.

## Correções anteriores do instalador — dev7

Base imutável: produto dev6 (`d974cea3cf3cb939fd7ae6147edb44d1c927847c2c4621d4da0a69d2cd4f0571`) e fontes dev6 (`000fd19df3af42c6afdff4145047fc7d851856b6d5e01134693c6bdce1ccabd2`). Foram conferidos os 144 arquivos do manifesto anterior antes da modificação. Nenhum comando Git foi usado. Os cinco extratores e o runtime privado permanecem iguais.

- `WindowsTasks.export` agora interpreta `EXCEPINFO.scode` quando o HRESULT externo é `DISP_E_EXCEPTION (0x80020009)`. A exceção exata enviada pelo usuário contém `ERROR_FILE_NOT_FOUND (0x80070002)` internamente. Somente esse código, ao consultar a tarefa, significa ausência. Consulta da pasta, conexão, acesso negado e `0x8004130F` continuam sendo erros: este último indica falta de informação da conta, não tarefa inexistente. O snapshot registra `had_task=false` e continua quando não há tarefa; não se suprime um erro de backup. O teste da dev6 considerava apenas HRESULT direto e não cobria o invólucro COM real informado.
- `Add-Routine` e `Remove-Routine` são ações comuns às páginas Destinos e Rotinas. A página 4 não chama mais `PerformClick` em controles ocultos da página 5. A remoção confirma, preserva o arquivo original, impede dependências inválidas, reorganiza a ordem e atualiza as duas tabelas. Adicionar preserva o contexto da página e abre o editor após a resposta da ponte. Controles de edição ficam indisponíveis durante a operação. Cadastro/descoberta usam identificador ASCII estável para nomes com acentos/espaços; o rótulo e o caminho não são alterados.
- O e-mail da página 3 é obrigatório. O botão Avançar acompanha a validade do campo e o handler também valida antes de mudar de página. A validação é sintática; não faz autenticação nem envia mensagem.
- O cabeçalho carrega o PNG CAIO diretamente e cria uma cópia independente da imagem; não converte o ICO em bitmap para o PictureBox. O ícone da janela e os assets CAIO do aplicativo são preservados. O quadrado relatado não pôde ser observado no host Linux; a alteração elimina essa rota de conversão, sem afirmar validação visual Windows.
- Novas configurações do wizard recebem dias coerentes com a frequência antes de abrir o editor: diária/every_run sete dias, weekdays segunda a sexta, weekly dia inicial. O prazo semanal inicial também acompanha o número de dias do calendário, como no cálculo legado de atraso. Importações e configurações existentes não são normalizadas silenciosamente. `Calendário: Personalizado` aparece quando os dias divergem do padrão, no editor nativo, no Qt e na tabela nativa. É um padrão de dias, não uma nova frequência de sucesso. Os demais dias semanais escolhidos explicitamente continuam oferecendo recuperação conforme o núcleo existente.
- O editor nativo usa TableLayoutPanel, linhas automáticas, painel rolável e botões separados no rodapé. `Set-NativeControlSizes` aplica a todos os inputs/botões do wizard e editor altura mínima de 36 pixels, a altura da fonte + 14 ou PreferredSize, o maior. Há escalonamento por DPI, tamanho limitado à área útil do monitor e navegação ancorada no rodapé; o conteúdo central pode rolar. Isso substitui os campos desenhados sobre labels e sem espaço suficiente. Escalas Windows reais não foram medidas.
- A mensagem passou a ser **Processando… acompanhe o log acima.**, com traduções EN/ES. No aplicativo, o status fica abaixo do log. A mesma exceção não é anexada duas vezes ao log nativo. Handles do processo da ponte são liberados também em erro.

Referências primárias consultadas: [Button.PerformClick no .NET Framework](https://referencesource.microsoft.com/System.Windows.Forms/winforms/Managed/System/WinForms/Button.cs.html), [escalonamento WinForms](https://learn.microsoft.com/en-us/dotnet/desktop/winforms/automatic-scaling-in-windows-forms?view=netframeworkdesktop-4.8) e [constantes do Agendador](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-error-and-success-constants). Os resultados locais estão na matriz; documentação não substitui execução nativa.

## Alterações do aplicativo na dev6 (preservadas)

- `ui.py` carrega o JSON completo em `assets/dashboard-theme.json`; paleta de todos os grupos, folhas de estilo, texto das células e cabeçalhos explícitos impedem herança de branco sobre branco. Checkbox tem marca vetorial local. Labels quebram linhas: as seis abas foram renderizadas em 1280×850 sem forçar 1576 pixels de largura, como ocorreu no primeiro ensaio.
- O acompanhamento agora fica em um splitter comum abaixo das abas. Diagnóstico, tarefas, exportações e execuções mostram andamento e resultados nessa região. Falhas e execuções sem elegibilidade têm mensagens próprias. Os controles de pausa/cancelamento da rotina afetam somente a seleção; cancelar lote continua abrangendo sua cadeia.
- `windows_identity.py` define o mesmo AppUserModelID para janela e atalhos, usando as APIs de propriedades do Windows já disponíveis em pywin32. Define comando/ícone de reabertura para a barra de tarefas. O ícone instalado usa nome derivado do hash, para não reutilizar o caminho antigo em cache. QSystemTrayIcon e showMessage recebem o ICO CAIO, sem ícone genérico. O health offscreen não tenta configurar um HWND Windows fictício.
- A interface única recebe pedidos de abertura em `state/open-interface.json`: uma segunda abertura traz a janela existente à frente e pode abrir o detalhe da notificação. O lock continua impedindo duas interfaces ativas.
- O EdgeDriver é preparado na abertura nativa, fora da thread gráfica, e antes de cada extração. A descoberta prioriza arquivos/raízes configurados e considera PATH, cache, pastas comuns e literais de scripts cadastrados (AST, sem executar o script). O resolvedor oficial tem fallback explícito se retornar versão incompatível. O original externo não é substituído; a cópia gerenciada mantém assinatura, compatibilidade e backup. A busca é limitada a 3.000 diretórios por raiz e quatro níveis, sem varredura indiscriminada de discos/rede.
- A pausa por rotina passou a afetar disparos automáticos. Disparo manual ainda respeita habilitação, dias e frequência; Forçar ignora frequência somente nessa execução. Caminho alterado não exige autorização por hash e erros ao salvar são exibidos no log.
- A aba de manutenção permite selecionar o destino de conectividade, inicialmente KWMS, sem depender de seleção oculta no Painel. A tabela de tarefas mostra atual/esperado; instalação/remoção atualizam também a preferência do monitor. Consulta COM distingue tarefa ausente de acesso negado, evitando informar remoção bem-sucedida após erro de consulta. A lista de backups permanece separada e tem mensagem de estado vazio.
- A atualização por ZIP foi mantida. A checkbox de feed sem função saiu do diálogo; o campo inativo continua explicado. Preferências e histórico foram exercitados pelos callbacks da GUI, incluindo JSON/XLSX. O JSON de tema e sua instrução de uso ficam no projeto e no pacote técnico para os próximos lançamentos.

A revisão reutiliza Qt, WinForms e pywin32; não acrescenta dependência de runtime. Os testes de propriedades Windows usam objetos COM simulados. A conferência nativa da barra de tarefas, cache do Explorer e notificações continua pendente. Ícones fixados manualmente antes desta identidade podem exigir desafixar/fixar; não se apaga o cache global do Windows nem atalhos externos.

## Correção anterior preservada (dev5)

A dev4 falhava antes de construir o formulário WinForms: `Read-NativeJson` enviava `locales.json` a `ConvertFrom-Json`, que recusa propriedades iguais sem distinguir maiúsculas de minúsculas. O catálogo continha `Desabilitada` e `desabilitada`, ambas com as mesmas traduções.

A dev5 mantém somente a chave canônica `Desabilitada`. A consulta Python passa a ignorar a caixa, assim como a consulta de propriedades usada pelo wizard. Português conserva o texto original; inglês e espanhol continuam traduzindo ambas as formas. Não foram adicionadas dependências, novos formatos de catálogo ou requisitos de PowerShell 7. A correção não usa `-AsHashtable`, indisponível no Windows PowerShell 5.1 que o iniciador chama.

O teste Python verifica a unicidade de todas as chaves do catálogo e as duas traduções do estado. O teste PowerShell agora lê o arquivo real com a mesma função do wizard e verifica suas traduções: antes, ele só analisava a sintaxe dos PS1 e um JSON sintético. Esse ponto cego permitiu a falha da dev4 apesar da suíte anterior aprovada. A reprodução e o resultado anterior à correção estão em `evidencias/dev5-reproduction.json` e `evidencias/dev5-regression-before.txt`.

Referência do comportamento do parser: [Microsoft — ConvertFrom-Json](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/convertfrom-json?view=powershell-7.4). A prova desta correção é a execução do leitor real, não apenas a documentação.

## Documentação consolidada

A consolidação da dev5 preserva três guias operacionais/técnicos. A dev6 acrescenta `AGENTS.md` como instrução de projeto para o tema e as próximas revisões:

| Documento vigente | Finalidade |
|---|---|
| `README.md` | Operação e instalação; copiado para `00 - Read Me.md` no ZIP do usuário |
| `docs/TECNICO.md` | Esta referência: código, build, compatibilidade e manutenção |
| `docs/VALIDACAO.md` | Matriz única de requisitos, resultados e limites |

Foram retirados `README_DESKTOP.md`, `README_TESTE.md`, `README_SCRIPTS.md`, os três `REGISTRO_*.md`, os três `MATRIZ_*.md` da raiz, `docs/COMANDOS.md`, `docs/COMANDOS_DESKTOP.md`, `docs/INSPECAO_E_BLOQUEIOS.md`, `docs/MIGRACAO_DESKTOP.md` e `docs/MATRIZ_ACEITE_DESKTOP.md`. O README legado foi substituído pelo guia atual. As informações úteis foram incorporadas aos três documentos vigentes; evidências antigas e capturas redundantes saíram da árvore ativa. O inventário está em `evidencias/dev5-doc-review.json`.

As versões anteriores continuam recuperáveis no snapshot imutável da dev4. Não se apagaram extratores, dados de produção, testes, licenças de dependências ou componentes de runtime. Esta limpeza afeta a documentação do projeto, não os avisos legais das bibliotecas.

Contradições resolvidas: entrega exclusiva de EXE, instalação manual de Python, uso de Git, caminhos pessoais, horários obrigatoriamente globais, autorização repetida por hash e consulta automática ao feed HTTPS não descrevem a edição atual. Textos antigos que afirmavam aplicativo ainda não implementado ou ATMS ausente também não são orientação vigente.

## Código e persistência

| Caminho | Responsabilidade |
|---|---|
| `native/Instalar.vbs`, `Instalar.bat`, `wizard.ps1`, `Native.Routines.ps1` | Iniciadores e wizard WinForms; formulários de rotinas |
| `native/Native.Common.ps1`, `Abrir.ps1`, `Update.ps1` | Ponte oculta, leitura JSON, abertura e espera do processo anterior |
| `orquestrador_app/native_bridge.py`, `native_install.py`, `native_updates.py` | Protocolo JSON, implantação transacional, integridade e ZIP local |
| `gui.py`, `ui.py`, `i18n.py`, `locales.json`, `dev_gui.py` | Interface Qt, tema, idiomas, controles e diagnóstico |
| `config.py`, `paths.py`, `sandbox.py`, `versioning.py` | Configuração, identificação, isolamento de teste e manifestos internos |
| `schedule.py`, `engine.py`, `worker.py`, `store.py` | Frequências, dependências, retries, extratores e SQLite |
| `files.py`, `io.py`, `script_versions.py`, `exporting.py` | Publicação, backup, locks, snapshots e exportações sanitizadas |
| `driver.py`, `connectivity.py`, `processes.py`, `runtime.py` | Driver, evidências de rede, processos próprios e console oculto |
| `agent.py`, `tasks.py`, `notifications.py` | Monitor, tarefa interativa e notificações |
| `scripts/`, `pipefy_orchestrator.py`, `automation_schedule.py` | Extratores e compatibilidade legada preservados |
| `desktop_tests/`, `tests/`, `tools/`, `build_inputs/` | Testes novos/legados, build e entradas fixadas |

A distribuição contém runtime privado Windows x64, PySide6 e dependências fixadas; não depende de Python global. O desenvolvimento usa venv. O monitor inicia pelo lançador do mesmo produto com `--agent`, usa tarefa própria com `InteractiveToken`, e serializa os trabalhos. Fechar a GUI não é desligar o monitor.

`same_chain` exige sucesso na mesma cadeia; `fresh_success` exige uma janela explícita. Falha, cancelamento, código 20 e bloqueio não registram sucesso. Os retries contam a primeira tentativa e respeitam orçamento por categoria e timeout total. Arquivo bloqueado reaproveita o staging para republicar. Não há retries externos de VPN/autenticação nem multiplicação de tentativas para código 20.

Os locks do sistema operacional protegem execução, perfil e publicação. Pausa é cooperativa em checkpoints; o timeout inclui a pausa. Cancelamento aguarda cooperação e encerra apenas processos próprios. Windows Job Object está implementado, mas não foi exercitado no host Linux. Temporários de falhas ficam disponíveis para diagnóstico; não há ação específica de limpeza na interface nem limite individual de tamanho para a captura stdout por execução.

## Build e testes reproduzíveis

Execute na raiz técnica, em ambiente de desenvolvimento. Estes comandos não são passos do usuário final. Use `uv sync --frozen` para criar o venv com o lock. Em Linux, defina `QT_QPA_PLATFORM=offscreen` ao testar sem monitor; em Windows, use a sessão gráfica autorizada.

```text
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy --platform win32
uv run --frozen python -m pytest -q --junitxml=docs/evidencias/dev9-tests.xml
uv run --frozen python -m orquestrador_app --health-check --health-output docs/evidencias/dev9-health.json
uv run --frozen pip-audit --disable-pip --no-deps -r docs/evidencias/native-audit-windows-inputs.txt --format json -o docs/evidencias/dev9-dependency-audit.json
```

O teste PowerShell deve passar **antes de empacotar**. No Windows, execute com o host realmente usado pelo VBS:

```text
powershell.exe -NoProfile -File tools/test_native_powershell.ps1
```

Em desenvolvimento Linux, `pwsh -NoProfile -File tools/test_native_powershell.ps1` verifica o parser JSON e os auxiliares portáveis; não substitui o teste acima nem abre WinForms.

O manifesto `build_inputs/windows-x64.json` fixa CPython Windows e wheels por URL/hash. Para preparar um runtime do zero e gerar o ZIP:

```text
uv run --frozen python tools/prepare_windows_payload.py --output build/runtime-windows --cache build/downloads
uv run --frozen python tools/build_native_zip.py --runtime build/runtime-windows --output build/release-dev10
uv run --frozen python tools/verify_native_artifact.py --archive build/release-dev10/CAIO_2.0.0.dev10.zip --scratch build/validation-dev10 --output docs/evidencias/dev10-artifact.json
```

Use uma área de saída nova: o builder não sobrescreve builds anteriores. Na dev10, o resultado contém `00 - Read Me.md`, `01 - Instalar.vbs`, `01 - Instalar(alt).bat`, `payload` e `diagnostics` no primeiro nível. `release.json` registra versão e hashes; o verificador extrai o ZIP e compara código, catálogo, iniciadores, logo, manifesto e PE gráfico x64. SHA-256 comprova integridade, não identidade do editor.

Na dev8 foi reutilizado o runtime da dev7 verificada, sem baixar novos binários ou mudar dependências. A poda mantém o conjunto de DLLs Qt necessário e licenças. `pefile` é dependência de build, não do usuário. Ferramentas PyInstaller de versões anteriores permanecem no código para compatibilidade; não são a rota de distribuição atual.

## CLI e compatibilidade

O usuário opera pela GUI. Para desenvolvimento, depois de configurar uma instalação isolada, `python -m orquestrador_app --data-root <pasta> ...` aceita `list-jobs`, `run`, `login`, `doctor`, `configure-schedules`, `--job`, `--force`, `--dry-run`, `--repair`, `--agent`, `--scheduled` e `--health-check`. Veja `--help` para a posição dos argumentos. `configure-schedules` abre a interface do produto.

O legado `pipefy_orchestrator.py --config <JSON> ...` e os CMD/PowerShell antigos continuam preservados no pacote técnico. Usam configuração, estado e modelo de disparos antigos; não são o caminho de instalação/execução da edição CAIO. A CLI nova não promete equivalência de todos os argumentos antigos, como `--config` e `--delay-seconds`.

O wizard nativo atual abre instalações de teste existentes e cria novas. Não oferece importação direta da instalação de produção v1.3.0. O importador legado existe na camada Qt/técnica: redireciona os caminhos ao ambiente de teste, não transfere sucessos nem tarefas de produção e deixa extras importados desabilitados. Não execute os antigos instaladores de tarefas junto do monitor novo.

## Backup, restauração e recuperação

Antes da ativação, a instalação guarda versão anterior, configuração, SQLite consistente, scripts adicionais, ponteiro de instalação, tarefa e atalhos próprios. Prepara a versão separadamente e valida hashes e saúde local. Falhas de cópia, migração, ativação ou health check acionam rollback; uma recuperação incompleta é erro visível. Atualização não depende de VPN ou extração corporativa.

O atualizador externo espera o PID e seu instante de criação para não confundir processos reutilizados. Não encerra processos alheios e não sobrescreve runtime em uso. A manutenção bloqueia execução ativa. Cancelamento durante cópia é cooperativo; interrupção abrupta é tratada pelo journal na próxima abertura.

Restauração de relatório adquire lock, verifica hash e guarda a versão atual antes da troca. Retenção por quantidade/idade/espaço preserva pelo menos o backup mais recente, mesmo se ele exceder sozinho o orçamento. Alteração do backup impede limpeza silenciosa. Eventos rejeita chaves vazias/ausentes e não publica novamente quando não há linhas novas. Separador e codificação precisam corresponder ao histórico existente.

Para recuperar configuração/estado, selecione um backup de **aplicativo** no fluxo de reversão; um backup de relatório não serve. Não edite manualmente ponteiros ou journals. A desinstalação remove ativação, tarefa e atalhos próprios e preserva dados; não equivale a purgar todo o diretório de versões/backups.

## Proveniência, versões e limites

Versionamento exclusivamente interno, sem novo branch/commit/tag. Na revisão dev5 foram conferidos os 181 arquivos do snapshot da dev4; esse registro abaixo é a proveniência daquela revisão. A entrega anterior tinha SHA-256 `a12c74e1e815b522ab9bc65f69a9b2b0c17f3d35c7f34c802e7c3b276e254935`; o código técnico, `481476e201ab231183521122022637e8c708728c1756a0ad7a3f71f5832914b5`. Manifestos desta revisão registram arquivos criados, alterados e removidos. Os cinco extratores são comparados byte a byte; não foram feitas extrações ou mudanças em produção.

O ensaio anterior de dev3/dev4 foi conservado em `evidencias/dev4-benchmark-comparison.json`: três processos por versão, CPython 3.12.14, Linux x64, Qt offscreen, timer de 10 ms por quatro segundos. Mediana de abertura aproximada: 0,189/0,299 s; RSS: 78,6/85,1 MiB; máximo de intervalo do timer: 26/16 ms. A dev4 aumentou abertura e RAM no ensaio, embora reduzisse redesenhos e pacote. **A dev5 não recebeu novo benchmark naquela revisão** e não há números de desempenho Windows.

Limites de validação permanecem em `VALIDACAO.md`. Não se afirma liberação por antivírus, assinatura própria, teste Windows sem Python ou homologação corporativa. A aprovação automática anterior de sintaxe não cobria o carregamento do catálogo; esta regressão agora tem verificação executável específica.

## Evidências anteriores — dev6

A base desta revisão é o ZIP técnico dev5, SHA-256 `80daf456ea540f83b4f2891266661d5aad2957f1f06a1308ebd9a90e06a29a71`, e o produto dev5, SHA-256 `4c8484935bb6ee676275764750c2ad53ffc353f3c29e2ded612f36c6fe9ccb2d`. Os 114 arquivos do snapshot dev5 foram conferidos antes da alteração. Não foi reutilizada como fonte a cópia de trabalho dev4 que ainda existia no ambiente. Os manifestos dev6 registram as diferenças e os hashes dos cinco extratores inalterados.

A suíte completa registrou 182 testes e 7 subtestes aprovados. `test_app_regressions.py` acrescenta 14 casos, incluindo renderização legível, atividade em todas as abas, ícones compartilhados, seleção/cancelamento, abertura única, troca de script pausado, reparação integral de driver local com backup, leitura AST sem importação, consulta COM ausente/acesso negado, tabela de tarefas, preferências e exportação pelos callbacks. Consulte `evidencias/dev6-*` para saídas, health, tipos, auditoria, PowerShell e artefato. Os comandos são os do guia, executados com `.venv/bin/python`, `.venv/bin/ruff`, `.venv/bin/mypy`, `.venv/bin/pip-audit` e `pwsh` no ambiente isolado; o lock foi conferido com `uv lock --check --offline`. As primeiras regressões identificaram a URI incorreta do checkmark SVG e uma expectativa de teste que tratava o histórico JSON como objeto em vez da lista contratada; ambas foram corrigidas antes da suíte final.

Benchmark dev5/dev6: três processos por versão, Linux x64/CPython 3.12.14/Qt offscreen, cache do sistema não limpo, timer de 10 ms durante quatro segundos. Medianas locais de abertura: 0,684/0,544 s; RSS: 81,2/82,3 MiB; mediana do maior intervalo de timer por amostra: 24,1/20,8 ms. Resultados brutos em `evidencias/dev6-benchmark.json`. É ensaio em host compartilhado, sem garantia de causalidade ou desempenho Windows; não se afirma redução de RAM. Nenhuma extração corporativa foi executada.

## Evidências anteriores — dev7

A falha com `(-2147352567, 'Exception occurred.', (0, None, None, None, 0, -2147024894), None)` foi reproduzida executando o backend da dev6, sem alterar o snapshot. `dev7-regression-before.txt` contém a falha esperada antes da correção. Os novos casos cobrem formas assinadas e sem sinal, HRESULT direto/interno, acesso negado, erro de conta e snapshot com tarefa ausente. A suíte de integração já existente mantém falhas induzidas e reversão de configuração, versão, estado, tarefas e atalhos.

`tools/test_native_powershell.ps1` carrega os arquivos reais e extrai os handlers do wizard pelo AST para executá-los com diálogos de teste. Exercita avanço com/sem e-mail, adição em ambas as páginas, remoção confirmada/cancelada, dependente e presets. Não abre WinForms e não consulta o Agendador real. O cadastro também é testado pelo protocolo JSON real da ponte, sem executar o script adicionado. Qt offscreen exercita Personalizado, retorno ao padrão, múltiplos horários e salvamento para as quatro frequências.

Consulte `evidencias/dev7-*` para a suíte, PowerShell, lint, formatação, tipos, saúde, auditoria, lock, preservação e pacote. Os comandos do guia foram executados no venv; o empacotamento reutiliza os binários da dev6 conferida. Não foi medido novo benchmark; não se atribui ganho de desempenho a esta revisão. WinForms, DPI, COM/Agendador e ciclo completo no Windows ainda não foram executados neste ambiente.

Resultado final: **191 testes e 7 subtestes passaram**, além de 25 verificações PowerShell. Lint/formatação/tipos e health offline passaram. A auditoria dos 41 pacotes fixados não encontrou vulnerabilidade conhecida; o lock de 72 pacotes foi validado offline. Nenhum desses resultados representa homologação no Windows real.

## Evidências anteriores — dev8

`dev8-regression-before.txt` registra a rejeição do XML equivalente no código anterior. A matriz contém a execução atual, com os resultados e limitações. O código adiciona testes de diferenças reais, defaults, contagens, registro COM, idempotência, tabela Qt e rollback. Não há dependências novas, extrações corporativas, alterações de produção ou novo benchmark de desempenho.

Resultado da revisão dev8: **221 testes e 7 subtestes passaram; 1 teste do Agendador Windows real não foi executado**. PowerShell 25 checks, lint, formatação, tipos, health e auditoria passaram. As evidências distinguem mocks/fixtures e execução Linux da homologação Windows ainda pendente.
