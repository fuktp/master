# CAIO — versão de teste 2.0.0.dev11

Aplicativo Windows de automação, com interface em português, inglês e espanhol. Esta revisão redesenha a interface a partir do tema KPMG Claro: navegação lateral, títulos e resumos claros, hierarquia de ações e campos legíveis. As correções do instalador e do Agendador da dev8 foram preservadas.


A dev10 aplica as melhorias operacionais avaliadas em [docs/VALIDACAO.md](docs/VALIDACAO.md): monitor com comunicação real, histórico paginado, configuração protegida contra edição concorrente, formulários guiados e prévias antes de operações em arquivos. Mantém o tema integral KPMG Claro e os cinco extratores originais. **Windows real ainda precisa de homologação.**


A dev11 reduz o rodapé **TESTE ISOLADO • caminho** a uma linha: caminhos longos recebem reticências e o endereço completo fica no tooltip. Corrige a saída dos processos para UTF-8 e lê logs antigos em CP1252 sem regravá-los. Inclui identidade própria dos processos CAIO e desinstalador com preservação dos dados.

## Downloads da dev11

- [Aplicativo completo com runtime privado](https://github.com/fuktp/master/raw/refs/heads/master/releases/2.0.0.dev11/CAIO_2.0.0.dev11.zip)
- [Fontes, testes, evidências e versionamento interno](https://github.com/fuktp/master/raw/refs/heads/master/releases/2.0.0.dev11/Fontes_CAIO_2.0.0.dev11.zip)
- [Hashes SHA-256 dos ZIPs](releases/2.0.0.dev11/SHA256SUMS.txt)

Extraia todo o aplicativo e abra `01 - Instalar.vbs`. O repositório mantém os pacotes anteriores. A homologação Windows continua pendente conforme a matriz de validação.

## Instalar ou atualizar

1. Extraia **todo o ZIP novo em uma pasta separada**. Não misture seu conteúdo com o ZIP anterior.
2. Abra **01 - Instalar.vbs**. A alternativa **01 - Instalar(alt).bat** pode mostrar brevemente uma janela de CMD.
3. Escolha o idioma e a ação. **Instalar / atualizar** cria uma instalação ou atualiza uma instalação de teste reconhecida; **Reparar instalação** repõe os componentes do pacote; **Abrir versão instalada** apenas inicia o aplicativo existente.
4. Escolha uma pasta vazia exclusiva do teste ou a pasta de uma instalação de teste existente. Não escolha a pasta de produção nem a pasta onde extraiu o ZIP.
5. Confira identificação, e-mail, destinos e rotinas. O e-mail é obrigatório: Avançar só fica disponível com um endereço válido. Edite frequência, dias, horários e ordem. Selecione o monitor somente se quiser execuções automáticas com a janela principal fechada.
6. Aguarde a validação automática, acompanhe o log central, revise as alterações e confirme a instalação. Ao terminar, abra o aplicativo pelos atalhos do produto.

Se a tentativa anterior foi revertida ao conferir a tarefa, abra o iniciador deste ZIP e selecione novamente a mesma pasta de teste reconhecida. Não apague configurações nem backups para repetir a instalação.

Depois de atualizar, confirme **CAIO • Teste 2.0.0.dev11** no título da janela. O atalho existente abre a versão apontada pela instalação. Se um ícone fixado manualmente na barra de tarefas ainda apontar para um lançador antigo do Python/WSH, desafixe-o e fixe a janela CAIO atual; a atualização não altera itens externos fixados pelo usuário.

Janelas, bandeja, atalhos e mensagens usam o mesmo ICO CAIO. Os atalhos passam a ter identidade própria do Windows e nome de arquivo de ícone baseado no conteúdo, evitando reutilizar o caminho do ícone antigo em cache. Abrir o atalho novamente solicita o foco da janela já aberta, inclusive para detalhes de notificações.

Python 3.13.16 e as bibliotecas estão incluídos em um runtime privado. O usuário não precisa instalar Python, pip ou executar comandos. A entrada continua sendo o VBS. O runtime inclui hosts gráficos com nomes e metadados CAIO: `CAIO-Orquestrador.exe`, `CAIO-Monitor.exe` e `CAIO-Rotina-Clientes.exe`, `Eventos`, `Procedimentos`, `KWMS` e `ATMS`. Scripts adicionais usam `CAIO-Rotina.exe`. São cópias do host Python com recursos de identificação e ícone CAIO; o código executável do interpretador permanece preservado. Esses hosts personalizados não têm assinatura própria. A apresentação e o agrupamento no Gerenciador de Tarefas ainda exigem conferência em Windows real. Mantenha a pasta `payload` junto dos iniciadores e não execute seus arquivos manualmente.

Requer Windows x64, sessão de usuário compatível e Edge para as rotinas de navegador. Scripts e pacote não têm certificado próprio. O iniciador não altera políticas persistentes nem desativa proteções: se a organização bloquear VBS/PowerShell/runtime, a TI precisa avaliar a execução. Trocar EXE por scripts não garante liberação pelo SmartScreen ou Defender.

## Abrir e desinstalar

Os iniciadores ficam visíveis tanto na raiz do ZIP extraído quanto na raiz da instalação:

- **02 - Abrir CAIO.vbs** abre o aplicativo instalado. Na pasta do ZIP, usa a última instalação de teste registrada neste usuário.
- **03 - Desinstalar CAIO.vbs** abre a confirmação de desinstalação. Também aparece em **Aplicativos instalados** do Windows para este usuário.
- As alternativas **02 - Abrir CAIO(alt).bat** e **03 - Desinstalar CAIO(alt).bat** podem mostrar brevemente um console.

A desinstalação exige fechar a interface e terminar as rotinas. Pela ação interna em Manutenção, a janela entrega o controle ao desinstalador e fecha. Cancelar a confirmação não altera a instalação. Confirmar encerra somente o monitor identificado desta instalação e remove tarefa, atalhos e registro próprios. A opção marcada remove versões verificadas de `app/versions` depois de o desinstalador fechar; pastas desconhecidas ou alteradas são preservadas. Configuração, relatórios, histórico, scripts e backups permanecem, incluindo uma cópia da versão atual para recuperação. Os iniciadores 03 permanecem para repetir uma limpeza interrompida por arquivo bloqueado. Nenhuma limpeza apaga dados de produção nem programas externos.

## Onde ficam os arquivos

| Dentro da pasta escolhida | Conteúdo |
|---|---|
| `app/versions` e `launch` | Versões instaladas, runtime privado e lançadores |
| `config.json` e `state` | Configuração, histórico SQLite, frequência e locks |
| `profiles/Edge-Teste`, `downloads`, `cache` | Perfil dedicado, temporários e driver gerenciado |
| `relatorios` e `logs` | Destinos de teste e registros de execução |
| `backups` | Versões anteriores dos relatórios; `backups/app` guarda o aplicativo |
| `extras` e `versionamento` | Scripts adicionais, snapshots e manifestos internos |

Os destinos, perfil, logs e driver gerenciados ficam dentro do ambiente de teste. OneDrive é detectado para identificação; gravar localmente não comprova sincronização. Os extratores Clientes, Eventos, Procedimentos, KWMS e ATMS foram preservados. Scripts adicionais são código local confiável, não executam em uma sandbox de segurança do Windows.

## Usar o aplicativo

Use a navegação lateral para alternar entre as seis páginas. A atividade permanece visível na parte inferior; arraste o divisor para ajustar sua altura. Botões azuis sólidos indicam a ação principal, contornados indicam alternativas e rótulos de cancelamento/remoção ficam separados pela intenção. Os resumos mostram a configuração salva; “Monitor configurado” não comprova que a tarefa esteja funcionando no Windows. O Histórico oferece Filtrar e Limpar filtros, com mensagem própria quando não há resultados.

- **Painel:** executar, forçar, simular, testar login e acompanhar estado/log. Uma rotina selecionada mostra ações individuais; várias mostram ações para o lote selecionado. Sem seleção, “Executar todas” fica separado. A barra aparece durante operações.
- **Rotinas e agendamentos:** habilitar, editar, cadastrar e excluir rotinas; definir horários próprios, dias, sequência, dependências, retries e timeout. Dependências, tentativas e calendário têm editores visuais; contratos adicionais continuam no JSON avançado validado.
- **Configurações:** idioma, e-mail, perfil, navegador visível/headless, destinos, retenção, notificações, histórico de Eventos e preferências portáveis. Exportação/importação mostra prévia e não transporta segredos nem caminhos de outra máquina.
- **Histórico e logs / Dev • Internos:** resultados e eventos correlacionados, estado interno, versões e autoteste local. Exportações sanitizadas em JSON e XLSX.
- **Diagnóstico e manutenção:** conectividade, EdgeDriver, tarefas, backup e restauração. A comparação de tarefas mostra valores efetivos/esperados, identifica os padrões do Windows e sinaliza diferenças reais. Passe o mouse nas células para ver o caminho técnico do campo. A tabela separada de backups só tem entradas depois de substituir um relatório válido.

Use **Controlar execução** no Painel para pausar, retomar ou cancelar uma rotina/lote. Sem seleção, aparecem as ações do lote; ao selecionar linhas, aparecem somente as ações pertinentes.

O painel de atividade central permanece visível em todas as abas e mostra andamento, avisos e resultado. As mensagens de inelegibilidade explicam quando nenhuma rotina rodou. Fechar a janela minimiza a interface; **Sair da interface** encerra-a. Uma execução em andamento requer manter o processo ou cancelar de forma controlada. Pausar agendamento impede novos disparos automáticos; a execução manual continua disponível e respeita frequência/dias, salvo Forçar. Uma rotina desabilitada continua bloqueada. Pausar execução espera um checkpoint seguro; não interrompe uma publicação no meio. Cancelar preserva o arquivo anterior e não registra sucesso.

### Novos fluxos da dev10

Em **Configurações > Preferências**, ajuste e-mail, destinos, retenção, temporários e avisos sem editar JSON. O modo Avançado permanece disponível. Sair com alterações oferece salvar, descartar ou cancelar; salvar detecta mudança feita em outra janela/processo.

No editor de rotina, configure dependências e tentativas por categoria, horários por dia, datas excluídas e pausa até data/hora com fuso. **Prévia semanal** mostra oportunidades; **Simular** mostra bloqueios e sucessos exigidos das origens. **Executar somente pendentes** usa a seleção, ou todas as pendentes quando não há seleção, e conserva as regras de sucesso/frequência.

O monitor mostra configuração, tarefa, processo e última comunicação separadamente. **Próxima elegibilidade** não promete horário efetivo de início: a fila aguarda a conclusão anterior. O monitor consulta mais lentamente em repouso e a tabela não é reconstruída a cada verificação. Desmarque **Acompanhar novas linhas** para consultar o log sem a rolagem voltar ao final.

No catálogo, importe uma pasta de script com auxiliares/recursos, revise o inventário e verifique bibliotecas sem executar a extração. Versões guardam notas e contrato; compare com a anterior antes de restaurar. Lixeira recupera o cadastro desabilitado com seu ID/histórico. Candidato abre em dados de teste separados e desabilitado; não representa isolamento de segurança do Windows.

Histórico tem páginas, total e filtros por nome/período/lote/categoria/texto. A central mantém avisos ligados à execução correta, inclusive silenciados. Exportações XLSX separam execuções/eventos e preservam conteúdos longos em partes numeradas. O pacote de suporte permite revisar uma amostra sanitizada antes da exportação.

Em manutenção, publicação/restauração mostram origem, destino, datas, tamanhos e hashes. Eventos com mesma chave e conteúdo diferente bloqueiam a publicação e preservam o histórico. Arquivos rejeitados gerenciados guardam motivo/hash e podem ser revalidados; selecione primeiro sua rotina no catálogo. Ocupação/limpeza exige prévia e protege relatórios e versões; o resultado de recuperação informa cada componente restaurado e intervenções pendentes.

### Frequências e monitor

| Frequência | Resultado esperado |
|---|---|
| Diária | Um sucesso por data local; horários seguintes recuperam pendências |
| Somente dias úteis / weekdays only | Diária de segunda a sexta, sem excluir feriados |
| Semanal | Um sucesso por semana de segunda a domingo; dia inicial e demais dias selecionados controlam elegibilidade e recuperação |
| Todos os horários / every_run | Uma execução por ocorrência própria, inclusive após sucesso no mesmo dia |

Em uma instalação nova pelo wizard, Diária e Todos os horários começam com os sete dias; Somente dias úteis começa de segunda a sexta; Semanal começa no dia inicial, segunda-feira por padrão. Para oferecer recuperação semanal em outros dias, selecione também esses dias. Configurações existentes conservam seus dias e pausas.

Use os botões dos dias e adicione um ou mais horários. O campo **Calendário** identifica **Padrão da frequência** ou **Personalizado** automaticamente. Personalizado descreve os dias e mantém a regra de sucesso escolhida em Frequência. Para voltar ao conjunto padrão, selecione Padrão da frequência. A política Somente dias úteis continua excluindo sábado e domingo. O tooltip mostra o dia completo. O editor usa campos com altura mínima calculada pela fonte, layout automático e rolagem, em vez de coordenadas sobrepostas. Alterar a ordem reposiciona as demais rotinas; dependências prevalecem sobre a sequência visual. Origem desabilitada ou sem o sucesso exigido bloqueia sua dependente. Sucesso anterior só vale com janela de validade explícita.

Uma instalação nova calcula as próximas execuções com agendamento ativo, mas **o monitor é opcional**. Sem instalar o monitor, a previsão não significa que exista uma tarefa automática. Instale-o no wizard ou em manutenção. Ele usa uma tarefa própria, verifica a fila e os avisos de atraso com a interface fechada e exige usuário conectado; não é serviço Windows. Uma atualização preserva pausas anteriores.

Horários simultâneos entram em fila, sem concorrência no perfil. O intervalo padrão é **30 segundos após terminar a rotina anterior**, configurável; não se aplica ao lote manual. O fuso vem do Windows. Horários perdidos são agrupados na ocorrência elegível mais recente da janela de recuperação, padrão 24 horas; não há repetição de todo o atraso. Uma ocorrência já tentada aguarda a próxima oportunidade.

**Forçar** ignora a frequência só naquela execução e não habilita uma rotina desativada. Login, diagnóstico, publicação local e restauração não contam como nova extração bem-sucedida.

### Scripts e versões

**Cadastrar script** seleciona um `.py`, inicialmente desabilitado. Nomes com espaços ou acentos mantêm o rótulo e recebem identificador interno compatível; o arquivo original é preservado. Revise subcomando, argumentos, ambiente, navegador, pasta de trabalho e saída antes de habilitar. Deixe o subcomando vazio para scripts sem CLI. As bibliotecas utilizadas precisam existir no runtime; não há instalação automática de dependências de scripts futuros.

Alterar o arquivo ou seu caminho não pede nova autorização por hash. Os hashes identificam snapshots e verificam integridade. **Versões do script** permite listar e restaurar cópias; a restauração cria uma cópia gerenciada sem sobrescrever o arquivo externo original. O snapshot de um script não inclui automaticamente arquivos auxiliares.

**Excluir rotina** pede confirmação. Por padrão retira apenas o cadastro, preservando histórico e versões. A opção adicional remove somente cópias gerenciadas; não apaga o script externo nem relatórios. Remova dependências que apontem para a rotina antes de excluí-la.

Substituir um extrator conhecido exige preservar seu contrato. Um script com funcionamento diferente deve ser cadastrado como adicional. As opções de URL substituem o endereço utilizado pelo adaptador quando este oferece suporte; não criam seletores ou um fluxo de login novo.

### Driver, conectividade e relatórios

O EdgeDriver é verificado antes das extrações. A preparação automática acontece ao abrir uma instalação nativa e antes das extrações, em segundo plano. A reparação procura caminhos configurados, PATH, caches Selenium, pastas comuns do usuário e caminhos literais de driver nos scripts registrados, sem importá-los; `driver_options.search_paths` permite acrescentar raízes. A busca é limitada por raiz e profundidade, prioriza locais configurados e não varre todo o disco. Selecionar um driver externo nas configurações preserva seu arquivo, registra-o como candidato e valida/copia para o cache da instalação. Sem candidato compatível, utiliza a resolução/download oficial existente e verifica versão e assinatura antes de usar a cópia gerenciada.

Em manutenção, escolha explicitamente o destino do teste de conectividade/VPN; KWMS é a seleção inicial quando disponível. O diagnóstico KWMS combina sinais de conectividade e do destino; quando necessário, verifica a resposta com navegador temporário próprio. Uma resposta vazia isolada permanece inconclusiva. No fluxo KWMS correspondente, mantém aviso, espera de 30 segundos e segunda tentativa; código 20 deixa a rotina pendente e continua o lote sem retries externos adicionais. SSO/MFA continua exigindo interação autorizada.

**Publicar arquivo local** valida um arquivo já baixado sem abrir navegador. Clientes, Procedimentos e ATMS usam seus validadores; Eventos mescla o histórico e deduplica pela chave configurada. Arquivo inválido, incompleto ou bloqueado não substitui o anterior. A publicação cria backup obrigatório antes da troca. Restaurar relatório preserva a versão atual e não registra uma nova extração.

## Backup, reparo e atualização

Use **Configurações > Atualização… > Atualizar por ZIP local…** ou abra o iniciador do pacote novo. O feed HTTPS fica indisponível e explicado nesta edição; não há consulta automática a servidor nem checkbox de verificação sem função. Salvar preferências de atualização oferece um seletor de destino JSON.

Se a conferência da tarefa encontrar diferença real, o instalador preserva o rollback e grava `state/task-registration-check.json` dentro da pasta de teste escolhida. O erro informa os campos e os valores encontrados; o arquivo mantém o diagnóstico completo mesmo após a reversão. O log agora separa a criação dos atalhos do registro da tarefa. Não apague configurações, tarefas ou backups para tentar novamente.

A atualização exige execução encerrada, cria backup de configuração, estado, scripts, versão, atalhos e tarefa própria, prepara outra pasta e faz verificações locais. Falhas internas acionam rollback. Falhas externas de VPN/servidor não são critério de atualização. Interrupções transacionais são tratadas pelo journal na abertura seguinte; uma recuperação incompleta permanece sinalizada como erro.

Para reparo, abra o wizard e escolha **Reparar instalação**. Para reversão, use **Reverter atualização** e selecione um backup gerenciado do aplicativo. Backups de relatório e de aplicativo são diferentes. Antes de copiar o runtime com monitor habilitado, uma tarefa temporária própria é registrada, consultada e removida; a evidência fica em `state/scheduler-preflight.json`. Recuperações geram `state/recovery-report.json`. A retenção dos relatórios limpa só itens gerenciados e preserva a versão mais recente; não apaga backups do aplicativo. A desinstalação preserva dados por padrão.

## Validação e documentação técnica

Esta é uma versão de teste. A comparação antiga foi reproduzida com XML sintético equivalente segundo o esquema do Windows. A nova comparação, o registro COM com objetos de teste e a instalação/reversão em diretórios temporários passaram na suíte local. Isso não identifica qual campo específico divergiu no seu computador: o log anterior não continha esses valores. O novo diagnóstico registra essa informação. **O fluxo completo em Windows real não foi homologado**: WinForms, atalhos, Agendador, login corporativo, VPN, Excel e ausência visual de console continuam pendentes.

O tema completo fornecido pelo usuário está em `assets/dashboard-theme.json` e é carregado pela interface. A regra de reutilização em próximos lançamentos está registrada em `AGENTS.md`, junto das convenções do projeto.

O pacote técnico contém três guias vigentes: este `README.md`, `docs/TECNICO.md` (build, compatibilidade, manutenção e histórico da revisão) e `docs/VALIDACAO.md` (matriz e evidências). Documentos antigos ficam apenas no snapshot anterior do versionamento interno. Não são instruções de instalação desta versão.
