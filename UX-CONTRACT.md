# UX Contract

## Product context

CAIO é um aplicativo Windows para operar extrações e rotinas locais. PT-BR, EN e ES; calendário/fuso da máquina, sem reinterpretar datas de execução. Meta de acessibilidade: WCAG 2.2 AA adaptada a controles desktop, com foco e teclado nativos. Conferência com leitor de tela e DPI Windows continua necessária.

## Business-context sources

| Escopo | Fonte | Consequência para a UI |
|---|---|---|
| Execução, agendamento e frequências | README.md — Frequências e monitor | Preservar os comandos e distinguir configuração de tarefa realmente instalada |
| Remoção e retenção | README.md — Scripts e versões / Backup | Manter confirmação, preservação e rollback existentes |
| Dados sensíveis e diagnóstico | docs/TECNICO.md — Código e persistência | Não expor credenciais nem adicionar chamadas corporativas em testes |
| Identidade e idioma | AGENTS.md / assets/dashboard-theme.json | Tema e ícone únicos, PT/EN/ES |
| Permissões, cobrança e legal | Sem mudança neste trabalho | Não introduzir regras ou alegações novas |

## Visual contract

DESIGN.md registra a intenção; assets/dashboard-theme.json é o dono dos tokens. Qt e WinForms são adaptadores desse JSON. Somente tema claro foi solicitado. A dev10 acrescenta regras de calendário, revisão concorrente e prévias descritas em docs/VALIDACAO.md; preserva o padrão especial KWMS, os extratores e o tema integral.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Table Selection | ui.configure_table / QTableWidget / HistoryModel | Este contrato e operações existentes em gui.py | Seleção local de linhas; ações do lote explicitamente nomeadas | test_app_regressions.py e test_ui_design.py |
| Select/Listbox | QComboBox / ComboBox WinForms | config.py e catálogos i18n | Nativo; geometria do popup da plataforma aceita | Teclado e popup Qt offscreen; Windows pendente |
| Date | TimesPicker / QTimeEdit / DateTimePicker WinForms | schedule.py e config.Schedule | Nativo HH:mm; dias via DaysPicker | test_schedule.py / test_caio_revision.py |
| Form | RoutineDialog / InstallWizard / Native.Routines | Validadores existentes em config.py | Modal de edição e wizard; sem substituir validação por cor | test_caio_revision.py / test_native_distribution.py |
| Scrollbar | ui.apply_theme / scrollbars nativas WinForms | DESIGN.md | Qt global; geometria nativa Windows | test_ui_design.py e capturas Qt |
| Toast | MainWindow.set_status / activity / notifications.show | gui.py e notifications.py | Status persistente, erro e aviso; notificação do sistema existente | test_app_regressions.py |
| CRUD | MainWindow e diálogos existentes | README.md e config.py | Salvar retorna à lista; cancelar edição não grava; excluir mantém confirmação | test_app_regressions.py / test_caio_revision.py |

## Dataset navigation

Rotinas são uma lista local de cadastros; rolagem nativa, sem paginação de servidor fictícia. Histórico usa QTableView/HistoryModel, páginas 25/50/100, total e filtros explícitos de Store.history_page. Backups exibem páginas de 100; tabelas auxiliares são limitadas. Exportação completa não herda o limite da tela. URL não se aplica a este app desktop; navegar entre páginas preserva os widgets e seus filtros. Não adicionar ordenação que invalide os índices usados pelos callbacks. Seleção com teclado e modificadores nativos; o título do grupo informa a quantidade selecionada.

Histórico vazio exibe uma instrução contextual. Sem resultados indica filtros ativos e oferece limpar. Nenhuma ação deve ser habilitada apenas por cor. Campos de filtro têm nomes acessíveis e botão de limpar; limpar atualiza imediatamente a lista e restaura o foco.

## Flow ledger

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome | Source ref |
|---|---|---|---|---|---|---|---|
| Create | Cadastrar script | Diálogo existente | Lista de rotinas | Atualização da lista | Erro e dados preservados no fluxo existente | Controle de origem | README.md — Scripts |
| Edit | Editar selecionada | Edição em modal | Lista existente | Status compartilhado | Validação mantém editor aberto | Controle de origem | config.validate / RoutineDialog |
| Delete | Excluir rotina | Confirmação existente | Lista atualizada | Estado persistente | Não remover em caso de falha/dependências | Lista | README.md — Scripts |
| Search | Filtrar / Limpar filtros | Leitura SQLite local | Mesma página | Estado vazio contextual | Filtros permanecem | Campo de filtro | Store.history |
| Bulk action | Executar lote selecionado | Progresso/etapa reais | Mesma seleção | Atividade persistente | Sem sucesso antecipado | Seleção atual | Engine.run |
| Cancel/back | Cancelar / navegação lateral | Nenhum trabalho novo | Contexto de origem | Sem gravação implícita | Formulários principais persistem entre páginas | Foco nativo | gui.py |

## Navigation and responsive behavior

QListWidget é o dono da navegação lateral, sincronizado bidirecionalmente com QTabWidget; setas e Tab são nativos. O título da janela acompanha a página e conserva produto/versão. Tabelas e JSON mantêm rolagem própria; ações quebram linha. Campos longos permanecem acessíveis por rolagem. A atividade continua em todas as páginas. Não há navegação web, drawer móvel ou regra 403 nova.

## Overlays and feedback

Qt QDialog/QMessageBox e WinForms Form/MessageBox existentes: modalidade, Escape, foco da plataforma. Ações perigosas preservam o diálogo de confirmação existente; não trocar por alert/confirm do navegador. Status de erro permanece em texto na atividade. Diálogos de edição conservam valores quando a validação falha. Os textos do usuário, caminhos, logs e JSON nunca são retraduzidos. Cancelar um editor alterado pede confirmação; sair de Configurações ou fechar com alterações oferece salvar/descartar/cancelar. Importação respeita a mesma proteção. Validação mantém valores; conflito de revisão exige recarregar e revisar.

## Async and resilience

Operações continuam pessimistas sob Task/Engine, com o bloqueio de duplicatas existente. Progresso não inventa porcentagem. Navegação não repete chamadas nem transforma erro de rede em sucesso. A dev10 move consultas e prévias longas para Task, preserva a revisão da edição, bloqueia duplicações e usa heartbeat com identidade do processo. Coleta sobreposta não cria fila ilimitada. Valores só são atualizados quando mudam; histórico emite dataChanged para linhas alteradas. Fontes: docs/TECNICO.md, observation.py, engine.py, store.py.

## Verification

Lint/formatação, mypy, pytest completo offline, health-check, checks PowerShell portáveis, auditoria Premium estática e build/verificador do ZIP. Capturas Qt em 1040 × 850 e 1440 × 940, seis páginas, editor e idiomas; teclado na navegação e popup de ComboBox. O auditor do plugin verifica o contrato, mas seu scanner HTML/CSS não cobre Python/PowerShell: testes e renderização Qt são a evidência de execução. WinForms, notificações, alto contraste, DPI e Agendador reais exigem Windows; não são comprovados pelo host Linux.


## Fluxos dev10

Configurações comuns têm formulários, JSON em Avançado e validação de e-mail junto ao campo. Dependências/tentativas/calendário têm editores próprios e conservam a regra interna KWMS. O monitor diferencia configurado, tarefa, processo e comunicação; próxima elegibilidade não equivale a início efetivo. Mensagens localizadas não reescrevem logs de scripts.

Publicação, restauração, limpeza, rotina e suporte apresentam prévia legível, estado de carregamento e ação explícita habilitada após leitura. Erros mantêm a prévia/valores. O commit revalida os arquivos; falhas não fecham a revisão nem sinalizam sucesso. Histórico e notificações se vinculam pelo ID da execução. A central resolve o clique ambíguo de balões sucessivos.

Acompanhamento de log pode ser desativado sem perder a posição. Preferências locais lembram tamanho, splitter, principais larguras, filtros e ordenação. Sem seleção, o painel mostra ações do lote; com seleção, ações da rotina/lote selecionado. Controles de pausa/retomada/cancelamento da execução ficam no menu Controlar execução, preservando área de tabela em janelas menores. Calendários de feriados só existem quando explicitamente nomeados/configurados.
