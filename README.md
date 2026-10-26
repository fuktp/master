# CAIO 2.0.0.dev14 — interface gráfica por scripts

O CAIO mantém as telas Qt, o tema KPMG Claro e os cinco extratores. Esta distribuição usa o **CPython 3.13.5 x64 corporativo**, por meio do `pythonw.exe` original aprovado pela TI. O ZIP não contém Python privado, executáveis CAIO, instalador, VBS, BAT ou PowerShell.

**Pacote de desenvolvimento para avaliação da TI em VM.** O incidente anterior não permite concluir a causa do bloqueio corporativo. Este formato não garante autorização por Defender, WDAC ou AppLocker. Não execute novos testes na estação afetada: a homologação deve ocorrer em VM Windows com políticas equivalentes, acompanhada pela TI.

## Preparação pela TI

1. Avaliar e provisionar CPython 3.13.5 x64, Qt/PySide6 e as dependências de `requirements-corporate.txt`. O arquivo fixa versões e hashes do lock; o programa não executa pip nem instala bibliotecas. Conferir os hashes do ZIP e de `portable-manifest.json`.
2. Extrair `CAIO_Portatil_Scripts_2.0.0.dev14.zip` em uma pasta de scripts aprovada, por exemplo `C:\Corporativo\CAIO`. Escolher **outra pasta exclusiva e vazia para dados**, por exemplo `C:\Dados\CAIO`. Os diretórios não podem conter um ao outro.
3. Criar um atalho comum diretamente para o `pythonw.exe` aprovado. Argumentos: `-B "C:\Corporativo\CAIO\caio_gui.py" --data-root "C:\Dados\CAIO"`. Pasta de trabalho: pasta dos scripts. Ícone: `assets\caio.ico`. Não utilizar iniciadores de versões anteriores.
4. Alternativamente, a TI pode criar esse atalho uma única vez com o próprio Python aprovado: `"C:\Python313\pythonw.exe" -B "C:\Corporativo\CAIO\caio_jobs.py" --data-root "C:\Dados\CAIO" --shortcut "C:\Users\USUARIO\Desktop\CAIO.lnk"`. O comando recusa substituir um arquivo existente. Não altera associações de arquivos nem o Menu Iniciar.

O Windows continuará mostrando os processos reais de Python, Edge e EdgeDriver. A janela CAIO pode aparecer entre as janelas no Gerenciador de Tarefas. Não há renomeação de executáveis, AppUserModelID próprio, registro em Aplicativos instalados ou alteração de políticas de segurança.

## Primeiro acesso

Abra o atalho. Escolha português, inglês ou espanhol, informe um e-mail válido e revise os destinos nos formulários. Cancelar não salva a configuração. O agendamento começa **pausado**; a execução manual e a simulação permanecem disponíveis.

Para migrar da dev12, selecione **Importar configuração e histórico…**, escolha a pasta de dados anterior e revise a prévia antes de confirmar. A importação copia o SQLite por sua API de backup, preserva regras de frequência/dependências/tentativas e rebasa os caminhos para a nova pasta. Não move nem apaga a origem, não copia cookies/perfil do Edge, remove argumentos/ambiente de máquina antigos e deixa scripts adicionais desabilitados para revisão. Relatórios e backups antigos não são importados automaticamente. Faça login novamente pelo botão **Testar login**.

As configurações continuam disponíveis em formulários e JSON avançado. Logs novos usam UTF-8; logs CP1252 antigos são lidos sem regravação. O rodapé ocupa uma linha.

## EdgeDriver

Ao abrir a interface, a verificação ocorre em segundo plano. Antes de uma rotina com navegador, a compatibilidade é conferida novamente. O driver fica em `dados\cache\driver\msedgedriver.exe`; a versão anterior é preservada em `previous`. A origem de download é exclusivamente `https://msedgedriver.microsoft.com`.

A versão deve compartilhar os três primeiros componentes com o Edge instalado. O programa consulta o canal oficial do major e considera a versão exata do Edge; escolhe a maior candidata compatível, sem rebaixar um driver compatível mais recente. A consulta bem-sucedida vale 24 horas; mudança da versão do Edge invalida o cache. **Verificar novamente** força nova consulta. O Edge não é atualizado pelo CAIO. Os quatro extratores Pipefy preservados exigem Edge e EdgeDriver 150 ou superior; a TI deve conferir esse requisito no navegador corporativo.

O ZIP, seus limites e CRC são verificados; a assinatura confiável Microsoft e a versão do arquivo são verificadas antes de executar `--version`. O driver só é ativado após essas verificações, sem execução própria em andamento. Não usa Selenium Manager para resolver downloads. A leitura de assinatura e versão utiliza PowerShell do Windows em comandos fixos de consulta, sem `Bypass` ou `EncodedCommand`. Se a política bloquear essas consultas ou o driver, a operação termina com diagnóstico para a TI, sem tentar alterar a proteção.

## Agendamento

Não há monitor residente. A TI pode importar uma tarefa claramente identificada `CAIO-Scripts-<id>` para executar `caio_jobs.py --tick` a cada minuto, com o Python original, na sessão do usuário conectado e com privilégio normal. Em **Diagnóstico e manutenção → Exportar tarefa para a TI…**, o CAIO gera o XML **desabilitado**; exportar não registra nem executa tarefas. A TI revisa e habilita a tarefa após os testes em VM.

`IgnoreNew` e locks impedem sobreposição. Cada verificação encerra após decidir e, se necessário, concluir o lote. Frequências de sucesso, dependências, recuperação de horários e intervalo padrão de 30 segundos continuam no motor existente. Verificações ociosas não criam execuções artificiais no histórico. O painel mostra a tarefa consultada, a última verificação e a atividade real; não espera heartbeat de um monitor inexistente. Avisos ficam na central e são apresentados com a interface aberta.

## Atualização e remoção

Feche execuções e interface. A TI pode substituir os scripts **no mesmo caminho aprovado** e revisar hashes/dependências. Não reutilize instaladores, atalhos ou tarefas de versões com runtime privado.

Para remover, a TI retira o atalho comum e a tarefa `CAIO-Scripts-<id>` correspondente e exclui somente a pasta dos scripts. **Preserve a pasta dos dados**, que contém configuração, histórico, relatórios, backups e perfil do navegador. Não há entrada de desinstalação no Windows. A ação **Remover arquivos do CAIO…** explica esse procedimento, sem apagar dados.

Detalhes: [referência técnica](docs/TECNICO.md) · [validação e pendências Windows](docs/VALIDACAO.md). Versões anteriores e seus guias permanecem nos snapshots de `Versionamento_interno`; não são instruções operacionais desta distribuição.
