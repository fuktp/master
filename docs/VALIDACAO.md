# CAIO dev14 — validação e critérios de liberação

## Escopo comprovado

Distribuição gráfica por scripts, perfil `portable_gui`, sem runtime privado nem executáveis CAIO. As evidências desta revisão são Linux, Qt offscreen e doubles/mocks; **não foi executado Windows, Defender corporativo, Agendador real ou extração corporativa**. O ZIP é de desenvolvimento para avaliação em VM pela TI, sem promessa de resolver o incidente da estação.

| Critério | Verificação disponível | Evidência |
|---|---|---|
| Preservação | Tema completo, ícone e cinco extratores comparados byte a byte com dev8 | `evidencias/dev14-preservation.json` |
| Regressões | Suíte padrão offline, incluindo contratos do motor, KWMS, publicação, backups, concorrência e cancelamento | `evidencias/dev14-tests.txt` |
| Novo perfil | Migração sem cookies/origem modificada, histórico, pastas separadas, tarefa desabilitada, locks, backend sem Qt, comandos no Python original | `desktop_tests/test_dev14_portable.py` |
| Driver | Cache/invalidação, versão, assinatura antes de executar, bloqueio por política e host de download restrito | Mesma suíte; confiança Windows simulada |
| GUI | Primeiro acesso, erros junto aos campos, mudança de idioma sem perder valores, ações sem instalador/AppID | Mesma suíte; Qt real offscreen |
| Idiomas | Pares EN/ES e placeholders, legendas próprias; conteúdo do usuário e logs externos preservados | `evidencias/dev14-localization.json` |
| Visual | Seis páginas em três dimensões, PT/EN/ES, primeiro acesso e editor de rotina | `evidencias/dev14-visual/capture.json` |
| Tipos/lint | Mypy com plataforma win32 e Ruff | `evidencias/dev14-types.txt`, `dev14-lint.txt` |
| Saúde | Bibliotecas, SQLite, cinco parsers e seis páginas sem rede | `evidencias/dev14-health.json` |
| Fluidez | Abertura, memória, CPU em repouso e intervalos do loop medidos no Linux | `evidencias/dev14-benchmark-linux.json` |
| Empacotamento | Sem EXE/DLL/PYD/PS1/BAT/VBS, CRC e hashes conferidos; autoteste a partir do ZIP extraído | `evidencias/dev14-artifact.json` |
| Compatibilidade histórica | Fluxos nativos anteriores continuam cobertos no repositório; não fazem parte deste ZIP | Suíte Python e `evidencias/dev14-powershell.json` |

A contagem final está em `evidencias/dev14-release-gate.json`. Resultados anteriores ficam nos snapshots dev8–dev13. A preservação das regras funcionais não equivale a homologar interfaces/SSO ou bibliotecas nativas em Windows Server.

## Pendências obrigatórias em VM Windows

A TI precisa preparar uma VM restaurável com Windows Server 2019, versão 1809, **Desktop Experience**, políticas corporativas equivalentes, CPython 3.13.5 x64 e dependências aprovadas. Não usar a estação afetada para tentativa e erro. Server Core e sessão sem desktop interativo não estão contemplados.

1. Registrar os eventos de Defender/EDR, AppLocker/WDAC e rede durante os testes, com a TI, para estabelecer o motivo de qualquer bloqueio. O programa não modifica essas políticas nem sugere desativá-las.
2. Validar assinatura/origem do Python, Qt, bibliotecas e scripts aprovados; confirmar inicialização pelo `pythonw.exe` original e atalho simples. Confirmar ausência de cópia/renomeação de Python, AppID próprio, entrada em Aplicativos instalados e associações de arquivo.
3. Confirmar primeiro acesso, cancelamento sem configuração, erros de e-mail/destino, migração da dev12, preservação dos originais/WAL/histórico e necessidade de novo login, sem importar cookies. Conferir troca de versão dos scripts no mesmo caminho, falha no commit e nova tentativa sem perda.
4. Revisar XML desabilitado e importar apenas a tarefa própria `CAIO-Scripts-<id>`. Testar habilitação, consulta COM, sessão do usuário, execução a cada minuto, pausa/retomada, horários perdidos, IgnoreNew, lock com lote manual e fim do processo após lote. Nunca tocar tarefas de produção nos testes.
5. Validar download Microsoft real, TLS/proxy, resposta de metadados, assinatura/cadeia Microsoft, bloqueio de assinatura e execução, versão incompatível, Edge atualizado, cache de 24 h, reconsulta manual, arquivo bloqueado e preservação da versão anterior. Confirmar que falhas param com diagnóstico para TI, sem resolvedor alternativo.
6. Exercitar os cinco extratores em destinos isolados, SSO/MFA, VPN, KWMS código 20, tentativas por categoria, dependências, duplicações, cancelamento, arquivos rejeitados e backup/restauração de relatório. Nenhuma extração corporativa ocorreu no Linux.
7. Conferir nomes reais e ícones de janela, atalho, item fixado, bandeja e notificações. A janela pode ser classificada como aplicação pelo Windows; não existe promessa de invisibilidade. Os processos reais continuam visíveis à TI.
8. Conferir PT-BR/EN/ES, datas/durações, teclado, foco, leitor de tela, contraste, logs com ã/é/í e DPI 100%, 125%, 150%, 200%. Qt offscreen não comprova renderização Windows nem Narrator.
9. Medir abertura, memória, CPU de GUI/worker/driver e resposta dos controles na VM e na sessão corporativa, sem retirar dependências antes dessa medição.
10. Remover somente atalho, tarefa própria e pasta de scripts; confirmar que dados/perfil/relatórios/histórico permanecem. Não executar desinstaladores de versões anteriores sobre a nova pasta.

**Liberação homologada permanece bloqueada até existirem essas evidências Windows e aprovação da TI.** O release gate registra explicitamente `windows_homologated: false`.
