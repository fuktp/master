# CAIO dev14 — referência técnica vigente

## Distribuição e fronteiras

`caio_gui.py` inicia o perfil `portable_gui` em `orquestrador_app.portable`; `caio_jobs.py` expõe somente verificação pontual, worker, autoteste e provisionamento explícito de atalho/XML. O Python corporativo e as dependências não fazem parte do ZIP. Windows exige CPython 3.13.5 x64 e o `pythonw.exe` original; Linux é permitido para testes de desenvolvimento. A escolha não constitui homologação de Windows Server 2019/1809 nem autorização corporativa.

O perfil desktop anterior continua no repositório para regressão e histórico. Seus instaladores e runtime não são entregues no ZIP portátil. O `agent.py` é excluído do pacote; a entrada antiga recusa `--agent`, desinstalação e registro de tarefas quando a configuração pertence ao perfil portátil. A interface pula identidade AppUserModelID/relaunch, registro Windows, wizard de instalação e troca automática de versão.

`processes.command` encaminha workers ao script `caio_jobs.py` usando `sys.executable` original. Não copia nem edita PE, não atribui nomes CAIO a executáveis e não procura hosts renomeados no modo portátil. Subprocessos não precisam de console; continuam identificáveis pelo sistema e pelas ferramentas corporativas. Locks de arquivo e Job Objects preservam cancelamento/limpeza somente de processos próprios. O programa não oculta sua existência nem contorna controles da empresa.

## Código e dados

`source_root()` identifica o código; `Paths.root` identifica os dados. A inicialização recusa pastas sobrepostas ou uma pasta não vazia sem propriedade reconhecida. `portable.json` marca a pasta de dados, sem `installation.json`, HKCU Uninstall ou atalhos automáticos. `install_root` aponta ao código, sem exigir cópia em `dados/app`. O perfil permanece isolado: perfil Edge, driver, temporários, logs e destinos gerenciados devem permanecer sob dados, conforme `sandbox.validate_isolation`. Isso evita adoção acidental de caminhos anteriores; não é uma sandbox de segurança para código arbitrário.

Configuração schema 2 mantém `execution_profile`, com desktop como default para compatibilidade. Salvamento atômico, revisão por SHA-256 e lock de commit impedem sobrescrita silenciosa de edição concorrente. O cache de configuração observa identidade/tamanho/mtime/ctime e devolve cópias independentes. JSON avançado não permite mudar o perfil pela GUI.

A migração é explícita, com prévia de origem, hash da configuração, histórico e novos destinos. O backup SQLite abre a origem em modo somente leitura e inclui dados confirmados no WAL. A cópia ocorre fora da thread gráfica, com limite de dois minutos. Configurações antigas não são sobrescritas. Cookies, perfil Edge e relatórios não são importados; argumentos/ambiente antigos são removidos e scripts adicionais ficam desabilitados. Falha anterior ao commit remove somente o banco novo incompleto e permite repetir a preparação na pasta própria.

## Contratos preservados

Os cinco arquivos de `scripts/`, `assets/dashboard-theme.json` completo e o ICO mantêm os hashes da dev8. Adaptadores em `worker.py` continuam definindo perfil, driver, destinos e publicação sem editar os extratores. Snapshots identificam a versão do script usada por execução. Os quatro extratores Pipefy conservam seu mínimo de Edge/EdgeDriver 150; compatibilidade entre driver e navegador, isoladamente, não comprova esse requisito dos extratores.

O `Engine` conserva ordem topológica, sucesso na mesma cadeia ou sucesso anterior com validade, frequência por sucesso/ocorrência, chaves únicas de proteção contra duplicações, recuperação de horários perdidos e pausa. Dias personalizados não alteram a frequência de sucesso. Permanecem horários por dia, exclusões explicitamente configuradas, intervalo padrão de 30 segundos e exceções por rotina. O KWMS mantém tratamento próprio de VPN/código 20: pendência não equivale a sucesso, e o lote pode continuar conforme as regras existentes.

Publicação valida o arquivo antes de substituir o destino; backup preserva a versão anterior. Restauração de relatório não simula nova extração. Eventos distinguem duplicata de conflito; arquivos inválidos permanecem na área de rejeitados. Histórico paginado e última execução por rotina continuam no SQLite. Exportação XLSX separa execuções/eventos e os detalhes longos. Evidências de suporte usam a sanitização existente.

## Verificações pontuais

O XML exportado parte do núcleo semântico de tarefas existente, mas aponta ao Python original com `-B caio_jobs.py --data-root ... --tick`. É desabilitado por padrão e não tem gatilho de logon. Usa calendário diário com repetição PT1M, `InteractiveToken`, `LeastPrivilege`, `IgnoreNew` e sem limite artificial de duração do lote. Importação/habilitação pertence à TI; a GUI não registra nem remove tarefas reais neste perfil.

`scheduler-tick.lock` coordena ticks. `execution.lock` continua exclusivo para lotes manuais/agendados; conflito registra verificação ocupada e encerra normalmente. Antes de chamar `Engine.run`, há simulação de elegibilidade: repouso não produz cinco registros de execução por minuto. O motor revalida as decisões sob o lock real. A tarefa encerra ao fim; não há Qt nem bandeja no backend. `scheduler-check.json` registra horário e conclusão/ocupação/falha. Consultas COM do Agendador ficam fora da thread gráfica, com cache de 60 segundos. Falha de consulta não é prova de ausência da tarefa.

A interface mantém suas notificações enquanto aberta. Fechar solicita saída após concluir operações já em andamento; não inicia outro monitor residente. Avisos agendados permanecem consultáveis no banco para o próximo acesso. O painel Dev mede processos reais, CPU por deltas, memória, locks e fila; não atribui um nome artificial a todo o conjunto.

## Atualização verificada do driver

`portable_driver.py` usa HTTPS, confiança TLS padrão e host exato `msedgedriver.microsoft.com`, inclusive antes de seguir redirecionamentos. Timeout de rede: 30 s por requisição. Metadados: 1 KiB; ZIP: 100 MiB; até 100 membros e 200 MiB descompactados. Apenas um membro com basename `msedgedriver.exe` pode ser escolhido; ele é gravado com nome fixo, sem extrair caminhos do ZIP. A leitura verifica o CRC do membro.

A consulta oficial `LATEST_RELEASE_<major>_WINDOWS` é comparada à versão exata do Edge. Candidatas exigem os três primeiros componentes iguais; a maior candidata compatível é selecionada, sem rebaixamento. Se o canal major já aponta a outro build, a versão exata do Edge é a candidata compatível disponível. A confirmação de quais versões a Microsoft efetivamente oferece ainda exige rede/Windows de homologação; nenhum fallback em mirror não oficial foi adicionado.

`Get-AuthenticodeSignature` consulta a confiança do Windows e exige Status Valid e certificado CN=Microsoft Corporation. `Get-Item` lê ProductVersion. São comandos fixos, com caminho transmitido como variável de ambiente; não há interpolação em código nem mudança de ExecutionPolicy. Somente depois de confiança/versão assinada é executado `--version`, que precisa confirmar a versão solicitada. Arquivo anterior permanece ativo até `os.replace` atômico, com cópia por hash em `previous/<hash>/msedgedriver.exe`. O lock de driver coordena workers; a GUI também detém o lock de execução antes de ativar. Falha de política, assinatura, sessão ou download não chama Selenium Manager, não modifica Edge/Defender/firewall/certificados e não escolhe outro nome/domínio para tentar passar pelo bloqueio.

Metadados de sucesso duram 24 h; mudança da versão completa do Edge invalida o cache. A assinatura do arquivo em uso é consultada antes de utilizá-lo. `Verificar novamente` ignora o cache. Diagnóstico fica em `state/portable-driver.json`; não é evidência de homologação do ambiente corporativo.

## Construção e verificação

```bash
.venv/bin/ruff check orquestrador_app desktop_tests tools caio_gui.py caio_jobs.py
.venv/bin/mypy --platform win32
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/python caio_jobs.py --health-check --health-output docs/evidencias/dev14-health.json
.venv/bin/python tools/audit_localization.py --output docs/evidencias/dev14-localization.json
.venv/bin/python tools/build_portable_zip.py --output build/release-dev14/CAIO_Portatil_Scripts_2.0.0.dev14.zip
```

`requirements-corporate.txt` exporta o uv.lock com hashes das dependências, sem bibliotecas de build/teste. A TI pode usar um wheelhouse corporativo e `pip --require-hashes --only-binary=:all:`; isso é provisionamento administrativo, nunca uma ação do CAIO. O pacote contém scripts/fontes necessários à GUI, recursos, requisitos e estes três guias. O builder rejeita extensões de payload fora da lista e verifica CRC/hashes de todos os arquivos. Os testes também recusam EXE/DLL/PYD/PS1/BAT/VBS no artefato.

Cada lançamento conserva `Versionamento_interno/<versão>-caio/{codigo.zip,manifesto.json}` imutáveis. Fontes e artefato publicados têm SHA256SUMS. A versão de desenvolvimento permanece distinta de uma versão homologada; veja [VALIDACAO.md](VALIDACAO.md).
