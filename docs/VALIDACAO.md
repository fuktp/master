# CAIO 2.0.0.dev10 — avaliação das 60 melhorias e evidências

## Resultado desta revisão

As propostas fazem sentido para a operação do CAIO. A implementação prioriza integridade dos dados, observação verdadeira do monitor, consultas menores, interface responsiva e formulários. Os complementos que precisam de Windows, de uma decisão de produto ou de um editor mais amplo estão identificados abaixo. **Implementado** descreve código e verificações locais; não significa homologação Windows.

Suíte offline: **255 testes e 7 subtestes aprovados; 1 teste Windows não executado**. PowerShell 7.6.8/Linux: **27 verificações** com doubles. Qt offscreen: seis páginas, três tamanhos (980×720, 1040×850, 1440×940), PT-BR/EN/ES e editor. Tipos, lint, formatação e saúde offline são conferidos nesta revisão. Tema completo e cinco extratores mantêm os hashes originais. Evidências atuais: `evidencias/dev10-*`; dev8/dev9 são históricas.

| Nº | Avaliação e entrega na dev10 |
|---|---|
| 1 | **Windows pendente.** Roteiro executável de instalação, atualização, reparo, cancelamento durante cópia, rollback, atalhos COM e execução agendada incluído no ZIP. Deve rodar numa VM limpa sem Python global; esta máquina Linux não comprova esse cenário. |
| 2 | **Implementado.** Antes de copiar o runtime, o instalador registra tarefa temporária UUID, desabilitada e sem gatilhos, consulta e compara o XML e remove somente a tarefa com propriedade confirmada. Sem execução. Diagnóstico em `state/scheduler-preflight.json`. |
| 3 | **Implementado.** Configuração, tarefa instalada, processo identificado, pausa, encerramento e comunicação são observações separadas. Consulta do Agendador com erro aparece como não verificada. |
| 4 | **Implementado.** Heartbeat com PID, nascimento do processo, horário e intervalo; informa última comunicação e avisa parada inesperada ou comunicação vencida. Não declara sucesso de rotina por heartbeat. |
| 5 | **Implementado.** Última tentativa e publicação consultadas diretamente por rotina, com índice. Teste inclui 1.101 execuções de outra rotina. |
| 6 | **Implementado no painel.** Etapa, categoria/causa conhecida, código e ação contextual: driver, login, conectividade, destino ou detalhes. Erros sem causa conhecida continuam identificados como tal. |
| 7 | **Implementado.** Recuperação registra seis componentes, erros e intervenção necessária; tenta os componentes independentes mesmo após falha de um deles. Teste de falha do Agendador confirma restauração dos outros componentes. |
| 8 | **Windows pendente.** Ícone e AppUserModelID comuns preservados. Roteiro confere metadados dos atalhos; janela, item fixado, bandeja e notificações precisam de inspeção visual real. |
| 9 | **Implementado.** Simulação não executa nem consome frequência; indica origens desabilitadas, sucesso na cadeia e sucesso anterior válido. Sucesso futuro aparece como condição, nunca como fato. |
| 10 | **Implementado.** Monitor verifica entre 1 e 30 segundos conforme execução e próxima oportunidade; repouso/pausa usam 30 segundos. |
| 11 | **Implementado.** Decisão lê último sucesso, período atual e maior ocorrência relevante; chaves únicas de período/ocorrência permanecem no SQLite. |
| 12 | **Implementado.** Cache limitado por identidade/tamanho/mtime/ctime; cada consumidor recebe cópia independente. Alteração externa invalida o cache. |
| 13 | **Implementado.** Células só recebem valores/estilos diferentes; o modelo do histórico emite alterações por linha. Seleção e rolagem persistem nas atualizações sem alteração da composição. |
| 14 | **Implementado para acompanhamento e operações longas.** Histórico, backups, snapshots, prévias, notificações VPN, diagnósticos e consultas do monitor usam tarefas de fundo. Pequenos commits atômicos de configuração/preferências continuam síncronos. |
| 15 | **Aplicação seletiva.** Histórico usa QAbstractTableModel/QTableView e páginas de 25/50/100. Backups exibem páginas de 100; tabelas pequenas continuam nativas. Evita uma migração sem benefício mensurável de todos os controles. |
| 16 | **Implementado.** Monitor e Dev importam tarefas/aviso VPN de módulo próprio; não importam a janela principal. |
| 17 | **Implementado.** Leitura incremental em blocos limitados com decodificação UTF-8, reconhecimento de rotação/truncamento e opção de acompanhar novas linhas. Desmarcar conserva a posição ao receber mensagens. |
| 18 | **Parcial, Windows pendente.** Benchmark real Linux registra abertura, RSS, CPU e latência do event loop; ferramenta acompanha o runtime para repetir em Windows. Uma amostra não sustenta promessa de ganho; nenhuma nova remoção de dependências. |
| 19 | **Implementado.** Formulários para e-mail, caminhos/destinos, retenção, notificações e temporários; JSON em Avançado, com sincronização explícita entre modos. |
| 20 | **Implementado.** Seleção de origens, modo de sucesso e validade em minutos no editor. Ciclos e origens ausentes seguem bloqueados. |
| 21 | **Implementado.** Campos por categoria para tentativas, espera, backoff e orçamento. VPN/autenticação externas ficam em uma tentativa; regra interna KWMS 2×30 s permanece intacta. |
| 22 | **Parcial.** E-mail tem indicação junto ao campo e descrição acessível. Demais validações conservam formulário e apresentam erro persistente; não há ainda associação de todo erro do JSON a um campo individual. |
| 23 | **Implementado.** Salvar/descartar/cancelar ao sair de Configurações, fechar ou importar; editor de rotina pede confirmação para descartar. Nenhuma gravação implícita. |
| 24 | **Parcial.** Lembra tamanho, splitter, acompanhamento do log, larguras de painel/histórico, filtros do catálogo e filtros/ordenação do histórico. Texto livre de busca do histórico não é persistido. Larguras das tabelas auxiliares ainda não. |
| 25 | **Parcial, Windows pendente.** Foco e teclado nativos, nomes acessíveis, altura de inputs e capturas em três tamanhos conferidos no Qt. Narrator, alto contraste e DPI 100/125/150/200% precisam de Windows. |
| 26 | **Parcial.** Catálogo PT-BR/EN/ES ampliado, datas/durações localizadas, códigos de estado/frequência/categoria apresentados como rótulos. Logs escritos por scripts e diagnósticos técnicos não são traduzidos; ainda falta revisão humana completa nos três idiomas. |
| 27 | **Implementado.** Manutenção separada em diagnóstico, tarefas, backups de relatórios e versões/ocupação do aplicativo. |
| 28 | **Implementado.** Horários por dia da semana; vazio usa a lista geral. Dias habilitados e frequência continuam obrigatórios. |
| 29 | **Implementado.** Prévia semanal com oportunidades, recuperação atual, motivos, janela e período. Não pressupõe que uma execução futura terá sucesso. |
| 30 | **Parcial.** Painel diz próxima elegibilidade; editor mostra horários e simulação mostra posição e intervalo. Horário efetivo depende da duração/conclusão anterior; não se fabrica previsão exata nem há cronograma gráfico da fila. |
| 31 | **Implementado.** Janela editável e explicação do agrupamento: somente oportunidade elegível mais recente, sem replay de todo atraso. Duplicações continuam impedidas. |
| 32 | **Implementado.** Pausa global e por rotina até data/hora com fuso; expira automaticamente. Pausa sem prazo permanece independente. |
| 33 | **Implementado.** Datas excluídas por rotina e calendário opcional com nome e datas explícitos. Nenhum feriado inferido. |
| 34 | **Implementado.** Exceção por rotina de 0 a 3.600 segundos; padrão global 30. Mantém contrato existente: intervalo entre rotinas do lote automático, não do manual. |
| 35 | **Implementado.** Executar somente pendentes considera seleção (ou todas sem seleção), inclui falhas/bloqueios/cancelamentos e mostra dependências antes. Não força nem ignora sucessos/frequência. |
| 36 | **Implementado.** Importação de pasta com entrada Python, auxiliares e recursos revisados; snapshot guarda inventário/hash e restauração cria cópia gerenciada. Perfis, ambientes, caches e arquivos sensíveis conhecidos são excluídos. |
| 37 | **Implementado com limite explícito.** Analisa imports sem executar a extração e consulta bibliotecas do intérprete ativo ao habilitar rotina desabilitada. Imports dinâmicos/extensões/condições de plataforma exigem teste no runtime Windows. |
| 38 | **Implementado.** Versão, notas, data, origem, inventário e contrato registrados no snapshot. Nome automático disponível quando não informado. |
| 39 | **Implementado.** Comparação com versão anterior mostra diff da entrada, arquivos alterados por hash e contratos antes/depois (argumentos, destino, ambiente e saída). Não há editor de merge. |
| 40 | **Implementado como ambiente de dados separado.** Candidato abre desabilitado em instalação de teste própria, sem ativação na produção. Não é sandbox de segurança do sistema operacional; execução exige revisão/habilitação nesse ambiente. |
| 41 | **Implementado.** Lixeira preserva ID/metadados/histórico; restaura desabilitado, valida conflitos/dependências e usa revisão de configuração. Exclusão explícita de cópias continua sendo irrecuperável por essa lixeira. |
| 42 | **Implementado.** Busca textual por nome/origem/categoria e filtros de habilitação/uso de navegador. |
| 43 | **Parcial.** Prévia de configuração portável/inventário, hashes, exclusões e bloqueio de possíveis segredos; exportação ZIP confirmada. A interface exporta o conjunto revisado; seletor individual de arquivos ainda não. Detecção automática não substitui revisão do conteúdo. |
| 44 | **Implementado.** Prévia de origem/destino, metadados/hash, integridade, contrato de workbook/chaves e backup antes da publicação; revalida arquivos no commit. Conflitos com histórico de Eventos continuam verificados na mesclagem. |
| 45 | **Implementado.** Duplicata idêntica é ignorada; mesma chave com conteúdo diferente bloqueia toda publicação, preserva histórico e registra até 100 divergências com total informado. Também detecta conflitos já presentes no CSV. |
| 46 | **Implementado.** Download gerenciado inválido é preservado em rejeitados com motivo/hash/execução. Selecionar rotina no catálogo e registro de rejeição permite revalidar e publicar com prévia; não apaga o original. |
| 47 | **Implementado no escopo proposto.** Comparação de datas, tamanhos e hashes antes de restaurar; explicita quando há igualdade. Diferença célula a célula não é inferida nem oferecida. |
| 48 | **Implementado.** Ocupação separada; limpeza manual com prévia e reconferência. Só logs próprios e temporários gerenciados antigos; relatórios, versões, rejeitados e arquivos não gerenciados ficam protegidos dessa ação. |
| 49 | **Implementado na prévia.** Diferencia gravação local e pasta indisponível; sincronização OneDrive/rede aparece como externa não verificada. Não promete confirmação de nuvem pela existência local. |
| 50 | **Implementado.** XLSX separa Execuções/Eventos. Conteúdo longo fica em partes numeradas numa aba própria, sem corte silencioso; fórmulas são texto literal e controles inválidos são escapados. Limite de linhas gera erro explícito e recomenda JSON. |
| 51 | **Implementado.** Histórico paginado com total, rotina por nome, período, lote, categoria e texto; tamanho explícito da página. JSON/XLSX de histórico completo não herdam o limite da tela. |
| 52 | **Implementado.** Central consultável mostra últimos 200 avisos, cada qual com execução correta. Clique da notificação abre a central; não usa a última mensagem como referência ambígua. |
| 53 | **Implementado.** Preferências por tipo, limites, horários de silêncio (inclusive meia-noite) e agrupamento. Avisos silenciados continuam na central; próximo aviso elegível informa quantos foram agrupados. |
| 54 | **Parcial.** Histórico de execução contém eventos correlacionados e registros de lote, tentativa, publicação/backup e snapshot. Dev permite inspecionar evidências; falta um navegador visual único entre todos os objetos. |
| 55 | **Implementado no Dev.** CPU por delta de tempo de processo (primeira amostra indisponível), RSS de processos próprios identificados por nascimento, fila ativa, checkpoints, locks e heartbeat. Não inventa CPU zero na primeira leitura. |
| 56 | **Implementado.** Prazo por rotina para aviso sem evolução baseado em checkpoint/etapa; ausência de log não mata processos. Timeout operacional já existente continua independente. |
| 57 | **Parcial.** Pacote sanitizado com período/rotina dos filtros, amostra revisável e exportação JSON/XLSX. Seleção individual de execuções ainda não; revisão de texto não garante remoção de todo segredo desconhecido. |
| 58 | **Implementado.** Hash de revisão + lock de commit comum detectam alterações externas antes de sobrescrever, inclusive editor de rotina aberto e cópias retornadas do cache. |
| 59 | **Windows pendente.** Capturas Qt/Linux atuais e verificações de geometria/idiomas preservadas; roteiro Windows exige telas, erros, carregamento, foco, contraste e escalas. Não há baseline visual Windows aprovado. |
| 60 | **Implementado como controle de versão de teste.** Snapshot/hashes, testes, benchmark, ZIP verificado e três guias alinhados. Liberação homologada continua bloqueada até evidências Windows; o pacote é identificado como dev/teste. |

## Homologação Windows a executar

Em VM Windows x64 limpa, sem Python global, extraia todo o ZIP e registre imagem/build do Windows, Edge, escala, idioma e software corporativo necessário. Use os iniciadores numerados para conferir o wizard real. O teste automatizado complementar é opt-in: `powershell.exe -NoProfile -File .\diagnostics\validate_windows_release.ps1 -Run -Output C:\evidencias\CAIO-dev10.json`.

O roteiro usa somente o Python do pacote e uma pasta temporária nova. Cria atalhos de teste dentro dessa pasta, sem substituir atalhos de outras instalações; instala/remove tarefa própria por identidade. Exercita backend real, COM, saúde do runtime e execução agendada de um marcador local. Isso **não testa cliques do wizard nem comprova ausência de Python global**: registre o inventário da VM e faça a parte visual abaixo. Não desative políticas persistentes para executar a ferramenta.

- Wizard: instalação, atualização na mesma pasta, reparo, cancelar antes/durante cópia e falha com rollback; conferir resultado por componente, dados e configuração.
- Agendador: sonda antes da cópia, usuário conectado, registro/consulta/remoção e execução própria; negar permissão deve falhar antecipadamente.
- App: janela, desktop, menu Iniciar, item fixado, bandeja e notificação; conferir ícone, reabertura e AppUserModelID entre processos.
- UI: seis telas, formulários, erros/carregamento, PT-BR/EN/ES, teclado, foco, Narrator, alto contraste e 100/125/150/200%.
- Operação corporativa: Edge/SSO/MFA/VPN, extratores, Excel bloqueado e destino/sincronização; não foram executados pela suíte local.
- Benchmark: usar `payload\runtime\pythonw.exe payload\src\release_tools\benchmark_gui.py --output C:\evidencias\benchmark-dev10.json`. Repetir em hardware/estado comparáveis, com janela visível, antes de afirmar regressão/ganho.

Os históricos de dev8/dev9 abaixo não substituem evidências desta revisão.

## Evidências históricas — dev8

Revisão de 22/10/2026. **Correção de software verificada; homologação completa em Windows pendente.** “Passou” abaixo indica o teste efetivamente executado em Linux, Qt offscreen ou PowerShell 7.4.13/Linux. Simulações de Windows não são testes nativos.

## Resultados executados — dev8

| Verificação | Resultado | Evidência |
|---|---|---|
| Suíte unitária, integração e regressão | 221 testes e 7 subtestes passaram; 1 teste Windows real não executado | `dev8-tests.txt`, `dev8-tests.xml` |
| Lint, formatação e tipos | Passaram; 54 arquivos formatados, 34 analisados por mypy | `dev8-lint.txt`, `dev8-format.txt`, `dev8-types.txt` |
| PowerShell: sintaxe, catálogo e handlers com doubles | 25 verificações passaram | `dev8-powershell.json` |
| Saúde local sem rede | Passou; cinco extratores e seis abas | `dev8-health.json` |
| Dependências e lock | 41 pacotes fixados sem vulnerabilidade conhecida encontrada; lock de 72 validado offline | `dev8-dependency-audit.json`, `dev8-lock.txt` |
| Preservação | 164 arquivos da base verificados; cinco scripts e runtime mantidos | `dev8-preservation.json` |
| Distribuição | ZIP novo; hashes, CRC, código, assets e PE gráfico conferidos | `dev8-build.json`, `dev8-artifact.json` |

## Correção solicitada — dev8

| Requisito | Implementação | Teste / resultado | Limitação |
|---|---|---|---|
| Rejeição da tarefa após registro | Comparação semântica de campos e padrões Windows | XML sintético equivalente falhou na dev7; passou na nova comparação | XML efetivo do computador do usuário não estava no log recebido |
| Registro de sessão compatível | API COM, definição integral, tipo de logon explícito | Chamada com flags 6 e InteractiveToken 3, cleanup em sucesso e erro | Objetos COM de teste; Windows real não executado |
| Não repetir registros equivalentes | Pré e pós-conferência usam o mesmo comparador | Duas chamadas de instalar geram um único registro | Sem Agendador real |
| Preservar erros reais | Sessão, privilégios, ação/diretório, horários e condições continuam verificados | 20 alterações negativas e três testes de quantidades rejeitados | Não testa políticas corporativas reais |
| Default correto | Padrões do esquema; ausência não herda o valor solicitado | Ausência de ExecutionTimeLimit implica 72 h e não é aceita como ilimitado | Campos verificados delimitados no código |
| Diagnóstico verificável | Arquivo com XMLs/valores/resultados antes da reversão | Arquivo real em diretório temporário, preservado após falha induzida | Contém identificação/caminhos locais, deve ser sanitizado ao compartilhar |
| Rollback continua obrigatório | Instalação real do núcleo com backend de teste que muda logon para S4U | Instalação normalizada conclui; alteração real reverte ponteiro, config, tarefa e atalhos | Runtime, links e registro de fixture; sem extração |
| Tabela e log coerentes | Mesmos checks do núcleo, defaults explícitos, aviso de revisão e etapa própria | Qt offscreen marca equivalentes OK e divergência como aviso | Não é renderização Windows |
| Agendador real reproduzível | Teste opt-in cria, lê, executa marcador e remove tarefa temporária | Não executado: host Linux e sem opt-in | Nenhuma homologação Windows inferida |
| Preservação | Snapshot dev7, cinco scripts, runtime, tema e wizard preservados | SHA-256 e manifesto da base | Originais e produção não alterados |

O log enviado comprova que o instalador chegou à conferência da tarefa e iniciou a reversão. Não comprova que a divergência era apenas de representação. A regressão demonstra um defeito concreto na comparação anterior; a nova versão corrige esse defeito, registra o motivo de qualquer diferença restante e mantém o bloqueio de incompatibilidades reais.

## Resultados anteriores — dev7

| Verificação | Resultado | Evidência |
|---|---|---|
| Suíte final, unitários/integração/regressão | 191 testes e 7 subtestes passaram | `dev7-tests.txt`, `dev7-tests.xml` |
| PowerShell: parser, JSON e fluxo dos handlers com doubles | 25 checks passaram em PowerShell 7.4.13/Linux | `dev7-powershell.json` |
| Lint / formatação / tipos | Passaram; 53 arquivos formatados e 34 analisados por mypy | `dev7-lint.txt`, `dev7-format.txt`, `dev7-types.txt` |
| Health offline Qt | Passou, versão dev7, cinco extratores | `dev7-health.json` |
| Auditoria dos 41 pacotes fixados | Sem vulnerabilidade conhecida encontrada | `dev7-dependency-audit.json`, `dev7-audit-log.txt` |
| Lock reproduzível | Validado offline, 72 pacotes | `dev7-lock.txt` |
| Base / extratores | 144 arquivos da dev6 conferidos; cinco scripts inalterados | `dev7-preservation.json` |
| Pacote novo | Gerado e verificado, código/assets/iniciadores correspondentes | `dev7-build.json`, `dev7-artifact.json` |

## Correções solicitadas nesta revisão — dev7

| Requisito | Implementação | Teste / resultado | Limitação |
|---|---|---|---|
| Backup falha ao consultar tarefa | HRESULT interno de DISP_E_EXCEPTION; somente arquivo/tarefa ausente retorna None | Exceção exata falhou no código dev6; quatro formas passam no código atual e permitem snapshot verificável | Backend COM simulado; Agendador Windows real não executado |
| Não ocultar erro real | Acesso negado, problema da conta e exceção sem evidência continuam falhando | Casos negativos e snapshot com had_task=false | Sem teste de permissões real |
| Quadrado no cabeçalho | PNG CAIO clonado diretamente; ícone próprio preservado | Asset preservado e presente no ZIP; fonte não usa Icon.ToBitmap | Renderização WinForms não executada; causa gráfica não observada neste host |
| E-mail antes de avançar | Validação no campo e no handler da página 3 | Handler real não avança vazio e avança com sintaxe válida; casos inválidos no PowerShell | Controles/diálogos de teste; não verifica existência da conta |
| Retirar/adicionar na página 4 | Ações compartilhadas chamadas diretamente | Handlers das páginas 4/5 executados com diálogos doubles; confirmação/cancelamento/dependências passaram | Cliques e diálogos nativos não observados |
| Script com espaços/acentos | Identificador estável; nome e original preservados | Protocolo real JSON adiciona rotina, impede duplicata e não executa fonte | Bibliotecas futuras não são instaladas automaticamente |
| Frequência inicial coerente | Presets somente ao criar nova configuração no wizard | Preview novo: diária/every_run sete dias, weekly um dia, weekdays cinco | Legado e estado já salvos preservados |
| Personalizado | Padrão de dias separado da regra de sucesso | Quatro frequências exercitadas em Qt offscreen; helpers reais no PowerShell | Editor nativo visual pendente |
| Tamanhos dos inputs | Layout automático/rolagem e mínimo por fonte em todo wizard/editor | Parser PS1 aprovado; implementação conferida | 100/125/150/200% DPI Windows não executados |
| Log acima | Texto PT/EN/ES e status abaixo do log Qt | Catálogo carregado no PowerShell; suíte GUI | WinForms real pendente |
| Não perder dev6/produção | Base, cinco extratores, tema e runtime preservados; nova versão interna | Hashes da base e comparação dos scripts; suíte isolada sem rede corporativa | Não há dados corporativos no teste |
| Distribuição | ZIP novo, VBS numerado, runtime privado, sem novo EXE próprio | CRC, hashes do payload, correspondência dos fontes e PE gráfico | Windows sem Python global não executado |

Os 25 checks do PowerShell incluem parser, catálogo real, e-mail, presets, handlers e auxiliares. **Doubles de diálogos não são execução WinForms.** A matriz consolidada abaixo conserva resultados anteriores; as evidências dev7 identificam a execução atual, sem reapresentar mocks como testes Windows.

## Resultados anteriores — dev6

| Verificação | Resultado | Evidência em `docs/evidencias` |
|---|---|---|
| Falha relatada no catálogo da dev4 | Reproduzida no leitor real do PowerShell | `dev5-reproduction.json` |
| Regressão antes da correção | Teste recusou 345 entradas com 344 chaves únicas | `dev5-regression-before.txt` |
| Suíte atual | 182 testes e 7 subtestes passaram | `dev6-tests.txt`, `dev6-tests.xml` |
| Leitura do catálogo, sintaxe PS1 e auxiliares | 11 verificações passaram | `dev6-powershell.json` |
| JSON do ZIP atual | Catálogo e tema completo lidos pelo PowerShell após extrair o ZIP | `dev6-packaged-json.json` |
| Lint, formatação e tipos | Passaram; 53 arquivos formatados, 34 analisados por mypy | `dev6-lint.txt`, `dev6-format.txt`, `dev6-types.txt` |
| Saúde do código | Cinco extratores, seis abas e oito páginas Qt; sem rede | `dev6-health.json` |
| Documentação herdada da dev5 | 15 documentos revisados, consolidados em três guias; instruções AGENTS adicionadas na dev6 | `dev5-doc-review.json` |
| Preservação | 114 arquivos do snapshot dev5 conferidos; cinco extratores e scripts nativos preservados | `dev6-preservation.json` |
| Dependências | 41 entradas fixadas auditadas; nenhuma vulnerabilidade conhecida encontrada; lock válido | `dev6-dependency-audit.json`, `dev6-lock.txt` |
| Pacote | Payload integral verificado; código e README correspondem aos fontes | `dev6-build.json`, `dev6-artifact.json` |

O teste PowerShell agora carrega o catálogo real; a versão anterior testava apenas a sintaxe dos scripts e JSON sintético. `health_check()` constrói a interface Qt e o wizard Qt de compatibilidade, não a janela WinForms. A distinção é necessária para não repetir a conclusão indevida de que esses testes comprovam a abertura do instalador Windows.

## Regressões do aplicativo verificadas na dev6

| Solicitação | Implementação | Teste executado / resultado | Limitação |
|---|---|---|---|
| Ícone na barra de tarefas/atalho | AppUserModelID comum, relaunch e ICO por hash | `test_windows_shortcut_and_window_use_same_app_id_and_hashed_icon` passou com COM fake | Shell/Explorer real não executado |
| Ícone da bandeja e notificações | Mesmo QIcon, overload de showMessage com ICO próprio | Comparação dos pixels e argumento da mensagem passou | Aparência nativa Windows não observada |
| Clique/segunda abertura traz o app | Pedido sob lock, ativação da janela existente | CLI sob lock real + refresh Qt passou | Foco/pin real Windows pendente |
| Guardar JSON para próximos lançamentos | JSON completo em assets, consumido pelo tema, regra AGENTS | Estrutura completa e presença no pacote verificadas | Persistência de projeto; não é instalação de plugin ou alteração de memória global do ChatGPT |
| Tabelas e inputs legíveis | Paleta explícita, foreground das células, marca checkbox | Texto renderizado escuro sem seleção, estados ativo/inativo, campos/labels passaram | Qt offscreen Linux; DPI Windows pendente |
| Janela cabe em tela menor | Quebra de labels e splitter ajustável | Seis abas renderizadas em 1280×850; relatório visual | Não mede escalas de DPI Windows |
| Log central e aviso em todas as páginas | Área comum, severidade e resumo de inelegibilidade | Visibilidade em todas as abas e callbacks passaram | Avisos de extração real dependem de sessão corporativa |
| Driver local/reparação | Busca ampliada + candidatos configurados + cópia validada | Ciclo ensure/repair/cópia/backup passou com arquivos de fixture | Assinatura/download oficial/Edge reais não executados |
| Script trocado e rotina pausada | Manual disponível; snapshot sem autorização repetida | Script trocado executado por worker real; sucesso persistido e agendamento permanece pausado | Script adicional sintético; contratos conhecidos preservados |
| Ação individual não atinge outras | Filtrar execuções pela seleção | Cancelamento de duas execuções de fixture afetou só selecionada | Sem navegador real |
| Preferências pela interface | Export/import com seletor e prévia | Callbacks reais geraram JSON e restauraram preferências | Diálogo nativo substituído por seletor de fixture |
| Histórico JSON/XLSX pela interface | Exportação em QThread | Arquivos reais gerados/lidos pelos testes | Dados sintéticos, sem extração |
| Tarefas organizadas e sem falso sucesso | Comparação visual, estado salvo, consulta COM com HRESULT | Tabela populada e HRESULT direto testado na dev6; HRESULT interno corrigido na dev7 | Agendador real pendente |
| Feed sem opção sem função | Removida checkbox, ZIP local permanece | Inspeção do diálogo e regressão nativa mantida | Reinício Windows real pendente |

## Matriz consolidada

Os números 1–23 correspondem aos critérios originais, com as alterações posteriores do usuário: ZIP/VBS substitui EXE próprio; versionamento interno substitui Git; instalação de teste não substitui produção.

| Requisito | Implementação | Teste executado | Resultado / limitação |
|---|---|---|---|
| 1. Preservação e isolamento | Snapshot dev4, hashes, sandbox de caminhos, pasta escolhida | Manifesto; `test_test_edition.py` | Passou; sem dados/estado corporativos reais |
| 2. Horário próprio fora dos globais | `schedule.eligible`, monitor por rotina | `test_own_time_outside_global_schedule` | Passou para 18:07; Agendador real pendente |
| 3. Daily e every_run | Períodos e ocorrências persistidos | `test_daily_multiple_opportunities_and_force_disabled`, `test_every_run_catch_up_collapses_and_persists_occurrences` | Passou; sem extração corporativa |
| 4. Semanal, reinício, atraso e fuso | Semana ISO, janela de recuperação, identidade da hora local | `test_schedule.py` | Passou com relógios controlados; mudança real de fuso Windows pendente |
| 5. Migração e GUI fechada | Tarefa própria e agente; teste não adota tarefas de produção | `test_real_background_agent_processes_queue_with_main_interface_closed`, XML de tarefa | Passou em subprocesso Linux; migração de produção não executada |
| 6. Dependências e ciclos | Grafo, same_chain/fresh_success, validade explícita, bloqueio propagado | `test_engine.py` | Passou; independentes continuam conforme política |
| 7. Conectividade inconclusiva | Evidências de DNS/TCP/HTTP/VPN | `test_connectivity_requires_multiple_signals`, teste de servidor indisponível | Passou com evidências simuladas; sem VPN corporativa |
| 8. KWMS 2 tentativas/30 s/código 20 | Adaptador mantém fluxo interno; sem retry externo | `test_kwms_schedule.py`, `test_new_kwms_adapter_two_attempts_30_seconds_then_pending` | Passou; espera solicitada de 30 s verificada por mock, sem sinalização Windows real |
| 9. Retries por categoria | Limite/backoff/timeout; bloqueio republica staging | `test_category_retry_limit_and_auth_no_loop`, teste de republicação | Passou com falhas simuladas |
| 10. SSO/MFA e login separado | Sessão interativa, teste de login não consome frequência | Teste de estado e inspeção do adaptador | Parcial; login corporativo real não executado |
| 11. Downloads inválidos/Excel | Validação antes de publicar, preservação do anterior | `test_files.py`, testes KWMS | Passou com arquivos sintéticos e PermissionError; Excel real pendente |
| 12. Backup, retenção e restauração | Catálogo com hashes, backup obrigatório, locks | `test_files.py` | Passou com arquivos reais sintéticos; OneDrive/compartilhamento Windows pendente |
| 13. Eventos e publicação local | Merge idempotente e validadores dos extratores | `test_events_idempotent_missing_keys_and_backup`, workers locais | Passou sem navegador e sem dados corporativos |
| 14. Concorrência e processos | Locks OS e encerramento de processos próprios | `test_processes_gui.py`, lock no engine | Passou Linux; Job Object/concorrência Windows pendentes |
| 15. Pausa, retomada, cancelamento | Checkpoints, revalidação e timeout cooperativo | `test_checkpoint_cancel_does_not_publish`, processos e cancelamento do instalador | Parcial; navegador real em pausa não exercitado |
| 16. Painel, avisos e monitor | Qt/QThread, fila deduplicada, atraso e agente | Testes GUI/timer e monitor em subprocesso | Passou local; notificação nativa e clique Windows pendentes |
| 17. OneDrive e outros usuários | Descoberta de contas, seleção explícita, caminhos isolados | Testes de contas múltiplas e espaços/acentos | Passou com entradas simuladas; registro Windows real pendente |
| 18. ATMS e extras | Cinco scripts preservados, cadastro e versões | Hashes; worker ATMS local; script adicional real | Passou; scripts desconhecidos/dependências futuras não homologados |
| 19. Windows sem Python/sem console | Runtime privado, pythonw PE GUI, VBS, subprocessos ocultos | Verificação estrutural do PE e flags | Parcial; execução completa em Windows limpo não feita |
| 20. Atualização e rollback | Journal, staging, backup e health sem rede | `test_install.py`, `test_native_distribution.py` com falhas induzidas | Passou com runtime/atalhos/tarefas de fixture; rollback Windows real pendente |
| 21. Agendador real | `schtasks`, sessão interativa e tarefa própria | XML, backend fake e diferenças | Não executado em Windows |
| 22. Wizard e pacote único | ZIP com VBS/BAT numerados, WinForms e aplicação Qt | Integridade do ZIP, leitura JSON real, parser PS | Pacote gerado/verificado; primeiro uso WinForms ainda não homologado |
| 23. Produto e atalho únicos | Um produto; atalhos na Área de Trabalho/Menu Iniciar; tarefa usa o mesmo lançador | XML/atalhos em backend de teste | Sem atalhos por extrator; COM Windows real pendente |
| Erro Desabilitada/desabilitada | Chave única; Python consulta sem distinguir caixa | Três novos casos Python + leitor real PowerShell | Passou; não exige instalar PowerShell 7 |
| Três idiomas | Catálogo compartilhado, seleção na interface | Teste Qt parametrizado PT-BR/EN/ES; duas formas de estado EN/ES | Passou; textos de scripts/logs externos não são traduzidos |
| Tema, logo e contraste | QPalette explícita, cores KPMG Claro, ICO | Asserções de paleta e presença/hash do ícone | Passou Qt/estrutura; DPI e renderização WinForms pendentes |
| Seletores de dias/horários/ordem | Botões com tooltip, vários horários, dropdown reposiciona ordem | `test_translated_visible_controls_selection_and_new_script_path` | Passou Qt; editor WinForms somente parser/revisão de código |
| Frequência weekdays e previsão inicial | Dias úteis e preview nativo ativo; pausa existente preservada | Testes weekdays e preview | Passou; monitor precisa ser instalado explicitamente |
| Fila de 30 s entre rotinas | `queue_delay_seconds`, espera após término anterior | `test_queue_delay_is_after_previous_finish_and_cancellable` | Início 0/35 s com rotina de 5 s em relógio simulado; sem benchmark real |
| Driver encontrado/reparado | Busca limitada, assinatura/versão, resolução oficial | Testes de candidatos/reparo e regressão legada | Passou com doubles; Authenticode/Edge reais pendentes |
| Conectividade usa regra KWMS | Sonda e is_empty_response, navegador temporário somente leitura | `test_kwms_diagnostic_uses_real_empty_response_rule_and_preserves_inconclusive` | Passou com navegador falso, sem consumir frequência |
| Troca e versionamento de scripts | Cadastro, snapshots e restauração em cópia gerenciada | Versões, remoção e worker real sem autorização por hash | Passou; auxiliares do script não são copiados automaticamente |
| Exclusão de rotina | Confirmação; cadastro apenas ou purga de cópias gerenciadas | Teste de remoção/reinclusão | Passou; original externo/relatórios/histórico preservados |
| Exportação/importação de preferências | Whitelist portátil, prévia e validação | `test_portable_round_trip_includes_language_delay_and_excludes_script_versions` | Passou; parâmetros de máquina não transportados |
| Histórico/Dev JSON e XLSX | Sanitização e neutralização de fórmulas | `test_json_xlsx_sanitization_and_formula_cells` | Passou com leitura real do XLSX |
| Tarefas sem null e relatório de diferenças | Retornos install/remove e comparação do XML | Testes de tarefas em `test_caio_revision.py` | Passou backend fake; falhas de consulta reais ainda exigem validação |
| Atualização sem feed HTTPS | Interface sem consulta ao feed; ZIP local verificado | Testes de ZIP, integridade e transação | Passou local; reinício Windows real pendente |
| Logs/progresso e painel Dev | Atualização por mudança, estados, leitura em thread e horário em segundos | Testes GUI/Dev/timer; inspeção dos callbacks | Passou Qt; nenhum percentual fictício e nenhuma evidência Windows inferida |
| Documentos vigentes sem conflito | README operacional + técnico + matriz única; builder usa README atual | Inventário dos 15 documentos e conferência do README empacotado | Consolidado; histórico anterior apenas nos snapshots |

## O que não foi executado

Windows PowerShell 5.1, WinForms real, duplo clique VBS/BAT, atalhos COM, Agendador real, instalação em Windows sem Python global, ciclo completo instalar/atualizar/reparar/cancelar/reverter, assinatura Authenticode real, SSO/MFA, VPN, download corporativo interrompido e bloqueio pelo Excel. Não há certificado próprio, liberação comprovada por SmartScreen/Defender nem benchmark Windows.

O teste padrão bloqueia rede corporativa e usa diretórios temporários. Não foram alterados agendamentos, perfis ou arquivos de produção. Os exemplos/falhas induzidas utilizam fixtures explícitas. Auditoria consulta vulnerabilidades conhecidas e não garante ausência de falhas.

Antes de aprovar produção, execute o teste PowerShell pelo host do iniciador e percorra o wizard/atualização em Windows autorizado e isolado. Confirme sessão, notificações, processos, tarefas e os casos corporativos acima. A versão entregue permite esse teste; a evidência local não o substitui.
