---
version: alpha
name: CAIO — KPMG Claro
description: Central de operações de automação Windows, com a identidade do tema fornecido pelo usuário.
colors:
  primary: "#00338D"
  action: "#005EB8"
  accent: "#00A3E0"
  surface: "#FFFFFF"
  canvas: "#F3F6FA"
  border: "#D7E0EA"
  text: "#333333"
  secondary: "#5B6770"
  success: "#2E7D32"
  warning: "#F5A623"
  danger: "#C0392B"
typography:
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "13.333px"
  heading:
    fontFamily: "Segoe UI Semibold, Segoe UI, sans-serif"
    fontSize: "24px"
rounded:
  DEFAULT: "6px"
  panel: "12px"
spacing:
  action-gap: "8px"
  panel-gap: "12px"
  page-inset: "20px"
components:
  button: { backgroundColor: "{colors.surface}", textColor: "{colors.action}", rounded: "{rounded.DEFAULT}", typography: "{typography.body}" }
  button-primary: { backgroundColor: "{colors.action}", textColor: "{colors.surface}" }
  button-danger: { backgroundColor: "{colors.surface}", textColor: "{colors.danger}" }
  table: { backgroundColor: "{colors.surface}", textColor: "{colors.text}", height: "44px" }
  table-header: { backgroundColor: "{colors.primary}", textColor: "{colors.surface}" }
  navigation: { backgroundColor: "{colors.primary}", textColor: "{colors.surface}", width: "204px" }
  page: { backgroundColor: "{colors.canvas}", textColor: "{colors.text}" }
  description: { backgroundColor: "{colors.canvas}", textColor: "{colors.secondary}" }
  status-success: { backgroundColor: "{colors.surface}", textColor: "{colors.success}" }
---

# CAIO Design System

## Overview

Uma central de operações para quem acompanha extrações, ajusta rotinas e investiga falhas em um computador Windows. O trabalho, e não uma página de apresentação, organiza a interface. A assinatura é a navegação azul KPMG permanente, junto de uma área de atividade compartilhada entre as seis páginas. A identidade vem do tema completo fornecido pelo usuário; não há uma nova marca, paleta ou biblioteca de UI.

Produto desktop; português brasileiro como idioma principal, inglês e espanhol disponíveis. O mercado de atuação não é inferido apenas pelo idioma. Não há escopo japonês. Referências de produto: README.md e docs/TECNICO.md. Antirreferências: gradientes decorativos, gráficos sem dados, números inventados, todas as ações com a mesma ênfase e campos menores que a fonte.

## Colors

O dono dos valores é **assets/dashboard-theme.json**, preservado integralmente. Este documento espelha os papéis aceitos (modelo B). Caminho único: JSON → `ui.theme()` → `ui.apply_theme()`/QPalette/QSS → controles Qt; JSON → `Read-NativeJson` → `Get-NativeThemeColor`/`Set-NativeTheme` → WinForms. A mesma identidade e ICO são usados em janelas, atalhos, bandeja e notificações.

| Papel | Chave do JSON | Consumidor |
|---|---|---|
| Marca e cabeçalhos | firstLevelElements / tableAccent | Navegação, títulos, cabeçalhos de tabela |
| Ação e seleção | accent | Botão primário, seleção e foco |
| Destaque decorativo | center | Borda superior de resumo e seleção da navegação |
| Superfície e fundo | background / backgroundNeutral | Tabelas, campos, página e atividade |
| Limites | shapeStroke | Bordas de campos e painéis |
| Texto | foreground / foregroundNeutralSecondary | Conteúdo e explicações |
| Semântica | good / neutral / bad | Mensagens, cautela e ações perigosas, sempre com texto |
| Alternância de tabela | visualStyles.tableEx.*.values[0].backColorSecondary | Qt e WinForms |

Tema claro institucional, inclusive em host com preferência escura. Ciano é destaque, nunca texto pequeno sobre branco. Avisos usam texto escuro e borda semântica; erro e sucesso também têm mensagens. Não se promete homologação de alto contraste do Windows em Linux.

## Typography

Segoe UI no corpo (10 pt), Segoe UI Semibold nos títulos (18 pt página, 12 pt seção). O frontmatter registra os equivalentes CSS a 96 DPI (13,333 px / 24 px), pois o linter aceita px e o Qt/WinForms usa pt. O sistema usa fallback local se a fonte não estiver instalada; não baixa fontes. Fontes, espaçamento e altura precisam continuar legíveis com textos PT/EN/ES longos. Entradas têm mínimo de 22 px de conteúdo mais padding no Qt; no WinForms `Set-NativeControlSizes` mede a fonte após tradução e escala. Validação de DPI Windows é separada.

## Layout

Navegação de 204 px; conteúdo flexível com margem de 20 px. Janela mínima 980 × 720. Barra lateral usa seleção e teclado nativos; o conteúdo preserva o estado ao navegar. Tabelas têm rolagem própria horizontal e vertical; não escondem colunas silenciosamente. Formulários longos usam QScrollArea, e ações usam FlowLayout compartilhado para quebrar linhas em janelas menores. O editor de rotina mantém ações fora da rolagem. O splitter permite ajustar a área de atividade sem eliminá-la.

## Elevation & Depth

Hierarquia por superfície clara, bordas e espaço. Sem sombra permanente ou blur. Diálogos nativos Qt/WinForms mantêm modalidade e foco da plataforma. A atividade não cobre conteúdo nem rouba foco ao atualizar.

## Shapes

Painéis com raio de 12 px, derivado de visualStyles.*.*.border[0].radius. Campos e botões Qt com 6 px. WinForms conserva a geometria nativa dos controles, explicitamente aceita; não imita cantos arredondados por desenho manual.

## Components

Botão padrão branco contornado, ação principal azul sólida, risco contornado com rótulo explícito. Hover, pressionado, foco visível e desabilitado são definidos no adaptador compartilhado. Progresso indeterminado somente durante trabalho real; sua área fica reservada em repouso. Não há animações decorativas.

Cabeçalhos de tabela azuis com texto branco, linhas alternadas e 44 px de altura Qt. A seleção é nativa, independente da cor de estado. ComboBox, tempo e diálogos usam comportamento de teclado da plataforma; suas opções permanecem localizadas. Logs e JSON são texto, não HTML. Conteúdo operacional usa verbos concretos e mensagens de recuperação existentes.

Verificação de deriva: `desktop_tests/test_ui_design.py` compara os papéis documentados com o JSON e exercita o adaptador em um tema alternativo de teste. O arquivo JSON e os cinco extratores devem manter os hashes do snapshot dev8.

## Do's and Don'ts

- Use o tema completo e os controles compartilhados em novas telas.
- Preserve frequência, dias, tarefas, backups e confirmação de ações existentes.
- Não crie uma variante de tema por tela nem use cor como único estado.
- Não trate screenshots Linux ou doubles PowerShell como homologação visual Windows.


## Operação dev10

O histórico grande usa modelo Qt e paginação; tabelas pequenas mantêm seleção e células estáveis. Formulários comuns substituem edição JSON no fluxo usual, com modo avançado explícito. Erros são texto persistente e indicação junto ao campo quando disponível. Monitor informa processo/tarefa/comunicação como fatos distintos. Prévia precede operações em arquivos e limpeza. Ação do lote e da seleção não competem em repouso; controles de execução ficam em menu próprio para manter a tabela legível em 980×720. O log aceita suspender acompanhamento sem pausar o processo.

## Ajustes dev11

O rodapé TESTE ISOLADO ocupa uma linha, com altura medida pela fonte. Caminhos longos recebem reticências no meio; tooltip e nome acessível retêm o endereço completo. A área de atividade continua redimensionável. Desinstalar CAIO usa o tema existente, mostra a pasta e os dados preservados, destaca a remoção em vermelho e dá foco inicial a Cancelar. Erro mantém a confirmação aberta; progresso indeterminado corresponde ao trabalho assíncrono real.

## Localização dev13

O catálogo é o dono dos textos de produto em PT-BR/EN/ES; os pacotes oficiais Qt complementam botões e calendário. Moldes preservam variáveis e não traduzem dados do usuário. Seletores de arquivo Qt passam a usar o diálogo Qt para respeitar o idioma escolhido; os controles do shell mantêm a aparência/idioma do Windows. A confirmação de retirada no wizard usa o mesmo tema, fonte, tamanho pela fonte e Cancelar como foco inicial. Não há mudança de paleta, ícone nem hierarquia visual.


## Perfil gráfico por scripts — dev14

A identidade KPMG, o tema completo e o ICO permanecem. O primeiro acesso reutiliza SettingsEditor, validação junto ao campo e rolagem de formulários; trocar PT/EN/ES preserva valores. Salvar grava dados em segundo plano e impede fechar durante o commit; cancelar antes do commit não salva configuração. Importar exige prévia explícita dos novos caminhos e preserva a origem, sem copiar perfil/cookies.

No perfil portable_gui, Diagnóstico exporta um XML desabilitado para revisão da TI, sem registrar/remover tarefas. Manutenção orienta remoção/substituição de arquivos e preservação dos dados. Não oferece instalador, atualização ou desinstalação de software. O painel mostra última verificação pontual e atividade, sem esperar heartbeat residente. Verificar novamente força consulta do driver com progresso/erro existentes. Fechar a GUI espera as operações de fundo já iniciadas e encerra; não inicia agente. O backend usa o Python original e permanece identificável pelo Windows.

As regras históricas de wizard/instalação deste contrato aplicam-se somente ao perfil desktop preservado, não à distribuição vigente. Donos canônicos: SettingsEditor para formulários, Task para operações de fundo, portable.py para preparação/importação/tarefa, portable_driver.py para atualização, MainWindow para ações e estado. Não duplicar paleta, seletor, validador ou editor de rotinas.
