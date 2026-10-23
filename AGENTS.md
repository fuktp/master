# Convenções do projeto CAIO

- Use `assets/dashboard-theme.json`, fornecido integralmente pelo usuário, como referência visual dos próximos lançamentos do aplicativo e dos dashboards CAIO: KPMG Claro, Segoe UI, azul #00338D, ações #005EB8 e destaque #00A3E0. Preserve o JSON completo, não apenas a paleta.
- Use o mesmo `assets/caio.ico` em janelas, atalho, bandeja e notificações. Não substitua por ícones genéricos do Qt/Python/WSH.
- Preserve o versionamento interno por snapshots e hashes, as fontes anteriores e os cinco extratores. O usuário também autorizou a publicação do projeto no repositório GitHub `fuktp/master`, branch `master`; mantenha o histórico remoto e não use push forçado.
- O produto de teste é entregue em ZIP com iniciadores numerados, wizard WinForms e runtime privado. Não exponha console; a alternativa BAT pode mostrar um flash transitório e deve ser identificada como alternativa.
- Testes padrão isolados, sem extração corporativa. Identifique testes Linux/mocks e verificações Windows reais separadamente. Não declare homologação por inferência.
- Mantenha somente README operacional, referência técnica e matriz de validação vigentes. Guarde documentação anterior no snapshot, evitando guias conflitantes na árvore ativa.
- Novos controles WinForms devem usar layout automático/rolagem e `Set-NativeControlSizes` para respeitar a altura real da fonte. Conferência visual de DPI exige Windows; parser e doubles não comprovam renderização.
- Calendário Personalizado descreve dias, sem criar uma nova frequência de sucesso. Presets só inicializam configurações novas; preserve dias e pausas já salvos.
- Compare tarefas pelo mesmo núcleo semântico usado na instalação e na GUI. Preserve defaults documentados, idempotência e rejeição de diferenças reais; mantenha diagnóstico por campo antes do rollback. O teste Windows do Agendador exige opt-in e não deve tocar tarefas de produção.
