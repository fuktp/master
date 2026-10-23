param(
    [string]$PackageRoot = '',
    [string]$DataRoot = '',
    [int]$OwnerPid = 0,
    [double]$OwnerStarted = 0,
    [string]$Backup = '',
    [switch]$AutoUpdate
)
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    . (Join-Path $PSScriptRoot 'Native.Common.ps1')
    Wait-OwnedParent $OwnerPid $OwnerStarted
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Este pacote exige Windows x64.' }
    if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { throw 'A política deste computador restringe WinForms/PowerShell. Solicite avaliação da TI.' }
    $script:payload = Get-NativePayload $PackageRoot $PSScriptRoot
    $script:release = Read-NativeJson (Join-Path $script:payload 'release.json')
    $script:visualTheme = Read-NativeJson (Join-Path $script:payload 'assets\dashboard-theme.json')
    if ($script:release.owner -ne 'orquestrador-native-package-v1') { throw 'Pacote não reconhecido.' }
    if (-not $DataRoot) {
        $DataRoot = Join-Path $env:LOCALAPPDATA 'Orquestrador-Teste\Ambiente-Scripts'
        $locator = Join-Path $env:LOCALAPPDATA 'Orquestrador-Teste\ultima-instalacao.json'
        if (Test-Path -LiteralPath $locator) {
            $remembered = Read-NativeJson $locator
            if ((Test-Path -LiteralPath (Join-Path $remembered.root 'instalacao-teste.json'))) { $DataRoot = $remembered.root }
        }
    }
    Set-NativeLanguage 'pt-BR'
    $script:languageChosen = $false
    $script:catalog = Read-NativeJson (Join-Path $script:payload 'src\orquestrador_app\locales.json')
    Initialize-NativeLanguage $DataRoot
    . (Join-Path $PSScriptRoot 'Native.Routines.ps1')
    $script:previewValue = $null
    $script:fillingConfiguration = $false
    $script:healthPassed = $false
    $script:job = $null
    $script:jobAction = ''
    $script:config = $null
    $script:pageIndex = 0
    $script:completed = $false
    $script:exitCode = 3
    $script:cancelPending = $false
    $script:pages = New-Object 'Collections.Generic.List[System.Windows.Forms.Panel]'
    $script:titles = @('Diagnóstico prévio', 'Local da instalação de teste', 'Usuário, computador e OneDrive', 'Destinos dos relatórios', 'Rotinas e horários próprios', 'Validação das dependências', 'Revisão das alterações', 'Instalação e verificação final')

    [Windows.Forms.Application]::EnableVisualStyles()
    $script:form = New-Object Windows.Forms.Form
    $form.SuspendLayout()
    $form.AutoScaleDimensions = New-Object Drawing.SizeF(96,96)
    $form.AutoScaleMode = 'Dpi'
    $form.Text = 'CAIO • Instalação e atualização'
    $form.Size = New-Object Drawing.Size(980, 760)
    $form.MinimumSize = New-Object Drawing.Size(980, 760)
    $form.StartPosition = 'CenterScreen'
    $form.Font = New-Object Drawing.Font([string]$script:visualTheme.textClasses.label.fontFace, [single]$script:visualTheme.textClasses.label.fontSize)
    $form.ForeColor = Get-NativeThemeColor 'foreground'
    $form.BackColor = Get-NativeThemeColor 'backgroundNeutral'
    $icon = Join-Path $script:payload 'assets\orquestrador.ico'
    if (Test-Path -LiteralPath $icon) { $form.Icon = New-Object Drawing.Icon($icon) }
    $script:title = New-Object Windows.Forms.Label
    $title.Location = New-Object Drawing.Point(28, 24)
    $title.Size = New-Object Drawing.Size(900, 38)
    $title.Anchor = 'Top,Left,Right'
    $title.AutoEllipsis = $true
    $title.Font = New-Object Drawing.Font([string]$script:visualTheme.textClasses.largeTitle.fontFace, [single]$script:visualTheme.textClasses.largeTitle.fontSize, [Drawing.FontStyle]::Bold)
    $title.ForeColor = Get-NativeThemeColor 'firstLevelElements'
    $form.Controls.Add($title)
    $script:subtitle = New-Object Windows.Forms.Label
    $subtitle.Location = New-Object Drawing.Point(30, 68)
    $subtitle.Size = New-Object Drawing.Size(900, 34)
    $subtitle.Anchor = 'Top,Left,Right'
    $brand = New-Object Windows.Forms.PictureBox
    $brand.SetBounds(870,12,64,64)
    $brand.Anchor = 'Top,Right'
    $brand.SizeMode = 'Zoom'
    $brandPath = Join-Path $script:payload 'assets\caio.png'
    if (Test-Path -LiteralPath $brandPath) {
        $brandSource = [Drawing.Image]::FromFile($brandPath)
        try { $brand.Image = New-Object Drawing.Bitmap($brandSource) } finally { $brandSource.Dispose() }
    }
    $form.Controls.Add($brand)
    $title.Width = 810
    $subtitle.Text = "TESTE ISOLADO • Versão $($script:release.version) • Runtime privado • Versionamento interno"
    $form.Controls.Add($subtitle)

    function New-Page {
        $panel = New-Object Windows.Forms.Panel
        $panel.Location = New-Object Drawing.Point(30, 112)
        $panel.Size = New-Object Drawing.Size(900, 510)
        $panel.Anchor = 'Top,Bottom,Left,Right'
        $panel.AutoScroll = $true
        $panel.Visible = $false
        $form.Controls.Add($panel)
        $script:pages.Add($panel)
        return $panel
    }
    function New-Label($Parent, [string]$Text, [int]$Top, [int]$Height = 55) {
        $label = New-Object Windows.Forms.Label
        $label.Text = T $Text
        $label.Tag = $Text
        $label.Location = New-Object Drawing.Point(0, $Top)
        $label.Size = New-Object Drawing.Size(870, $Height)
        $Parent.Controls.Add($label)
        return $label
    }
    function New-Grid($Parent, [int]$Top, [int]$Height) {
        $grid = New-Object Windows.Forms.DataGridView
        $grid.Location = New-Object Drawing.Point(0, $Top)
        $grid.Size = New-Object Drawing.Size(890, $Height)
        $grid.AllowUserToAddRows = $false
        $grid.AllowUserToDeleteRows = $false
        $grid.RowHeadersVisible = $false
        $grid.AutoSizeColumnsMode = 'Fill'
        $grid.BackgroundColor = (Get-NativeThemeColor 'background')
        $grid.EnableHeadersVisualStyles = $false
        $grid.ColumnHeadersDefaultCellStyle.BackColor = (Get-NativeThemeColor 'tableAccent')
        $grid.ColumnHeadersDefaultCellStyle.ForeColor = (Get-NativeThemeColor 'foregroundLight')
        $grid.ColumnHeadersDefaultCellStyle.WrapMode = 'True'
        $grid.ColumnHeadersHeightSizeMode = 'AutoSize'
        $grid.DefaultCellStyle.BackColor = (Get-NativeThemeColor 'background')
        $grid.DefaultCellStyle.ForeColor = (Get-NativeThemeColor 'foreground')
        $grid.DefaultCellStyle.SelectionBackColor = (Get-NativeThemeColor 'accent')
        $grid.DefaultCellStyle.SelectionForeColor = (Get-NativeThemeColor 'foregroundSelected')
        $grid.AlternatingRowsDefaultCellStyle.BackColor = ([Drawing.ColorTranslator]::FromHtml([string]$script:visualTheme.visualStyles.tableEx.'*'.values[0].backColorSecondary.solid.color))
        $grid.SelectionMode = 'FullRowSelect'
        $grid.MultiSelect = $false
        $grid.AutoSizeRowsMode = 'AllCells'

        $Parent.Controls.Add($grid)
        return ,$grid
    }
    function New-TextArea($Parent, [int]$Top, [int]$Height) {
        $text = New-Object Windows.Forms.TextBox
        $text.Location = New-Object Drawing.Point(0, $Top)
        $text.Size = New-Object Drawing.Size(890, $Height)
        $text.Multiline = $true
        $text.ReadOnly = $true
        $text.ScrollBars = 'Both'
        $Parent.Controls.Add($text)
        return $text
    }
    $page = New-Page
    New-Label $page "Este assistente instala somente na pasta de teste escolhida. Aplicativo, configuração, perfil do Edge e relatórios permanecem isolados. É possível voltar e cancelar antes de aplicar." 0 75 | Out-Null
    $script:operation = New-Object Windows.Forms.ComboBox
    $operation.DropDownStyle = 'DropDownList'
    $operation.Location = New-Object Drawing.Point(0, 85)
    $operation.Width = 600
    $operation.Items.AddRange(@('Instalar / atualizar', 'Reparar instalação', 'Abrir versão instalada'))
    $operation.SelectedIndex = 0
    $page.Controls.Add($operation)
    $operationHelp = New-Label $page 'Instalar cria um ambiente isolado; atualizar preserva os dados. Reparar repõe os componentes do pacote. Abrir inicia a versão já instalada sem alterar arquivos.' 125 68
    $operationDescriptions=@('Instalar cria um ambiente novo na pasta escolhida. Atualizar preserva configurações, scripts e histórico de uma instalação de teste existente.','Reparar verifica e repõe os componentes desta versão. Mantém os seus dados e configurações e cria backup antes de aplicar.','Abrir inicia a versão instalada na pasta escolhida. Não instala, atualiza ou altera arquivos.')
    $operationHelp.Tag=$operationDescriptions[0]; $operationHelp.Text=T $operationHelp.Tag
    $operation.Add_SelectedIndexChanged({if($operation.SelectedIndex -ge 0){$operationHelp.Tag=$operationDescriptions[$operation.SelectedIndex];$operationHelp.Text=T $operationHelp.Tag}})
    $languageChoice = New-Object Windows.Forms.ComboBox
    $languageChoice.DropDownStyle = 'DropDownList'
    $languageChoice.SetBounds(620,85,265,30)
    $languageChoice.Items.AddRange(@('Português (Brasil)','English','Español'))
    $languageChoice.SelectedIndex=[Array]::IndexOf(@('pt-BR','en','es'), $script:language)
    $languageChoice.Add_SelectedIndexChanged({
        if (-not $script:fillingConfiguration) { $script:languageChosen=$true }
        Set-NativeLanguage (@('pt-BR','en','es')[$languageChoice.SelectedIndex])
        if ($null -ne $script:config -and -not $script:fillingConfiguration) { Collect-Configuration; Refresh-RoutineRows }
        foreach($panel in $script:pages){ Translate-Controls $panel }
        Show-Page $script:pageIndex
    })
    $page.Controls.Add($languageChoice)
    $diagnostic = New-TextArea $page 365 130
    $policyGrid = New-Grid $page 200 155
    $policyGrid.Columns.Add('scope','Escopo') | Out-Null
    $policyGrid.Columns.Add('policy','Política') | Out-Null
    $policyGrid.Columns.Add('meaning','O que controla') | Out-Null
    $policyGrid.Columns[2].FillWeight=240
    $policyGrid.ReadOnly=$true
    $meanings=@{MachinePolicy='Política da organização para o computador';UserPolicy='Política da organização para o usuário';Process='Somente esta janela do instalador';CurrentUser='Preferência do usuário';LocalMachine='Preferência do computador'}
    foreach($policy in Get-ExecutionPolicy -List) {
        $policyGrid.Rows.Add([object[]]@([string]$policy.Scope,[string]$policy.ExecutionPolicy,$meanings[[string]$policy.Scope])) | Out-Null
    }
    $diagnostic.Tag = "Usuário: {0}`r`nComputador: {1}`r`nPowerShell: {2}`r`nIdioma de execução: {3}`r`nO parâmetro Bypass afeta apenas este processo. Políticas da organização, Smart App Control, antivírus e Windows Script Host continuam aplicáveis. Nenhuma política do computador será alterada."
    $diagnostic.Text = T $diagnostic.Tag @($env:USERNAME,$env:COMPUTERNAME,$PSVersionTable.PSVersion,$ExecutionContext.SessionState.LanguageMode)

    $page = New-Page
    New-Label $page 'Escolha uma pasta vazia ou uma instalação de teste reconhecida. Os arquivos originais de outra instalação serão recusados e preservados.' 0 70 | Out-Null
    $script:rootBox = New-Object Windows.Forms.TextBox
    $rootBox.Location = New-Object Drawing.Point(0, 85)
    $rootBox.Width = 885
    $rootBox.Text = $DataRoot
    $page.Controls.Add($rootBox)
    $browse = New-Object Windows.Forms.Button
    $browse.Text = 'Escolher…'
    $browse.Location = New-Object Drawing.Point(0, 125)
    $browse.Width = $rootBox.Width
    $browse.Add_Click({
        $picker = New-Object Windows.Forms.FolderBrowserDialog
        $picker.Description = T 'Selecione ou crie uma pasta exclusiva para o teste'
        $picker.SelectedPath = $rootBox.Text
        if ($picker.ShowDialog() -eq 'OK') { $rootBox.Text = $picker.SelectedPath }
        $picker.Dispose()
    })
    $page.Controls.Add($browse)
    $script:locationStatus = New-Label $page 'O diretório será validado ao avançar. Não é necessário instalar Python nem executar comandos.' 175 140

    $page = New-Page
    $script:identityText = New-TextArea $page 0 280
    New-Label $page 'E-mail obrigatório para os extratores. Informe um endereço válido; não informe senha.' 300 32 | Out-Null
    $script:email = New-Object Windows.Forms.TextBox
    $email.Location = New-Object Drawing.Point(0, 335)
    $email.Width = 700
    $email.Add_TextChanged({
        if ($script:pageIndex -eq 2 -and $null -eq $script:job) { $next.Enabled = Test-NativeEmail $email.Text }
    })
    $page.Controls.Add($email)
    New-Label $page 'Contas OneDrive são exibidas para identificação. Esta edição mantém os relatórios dentro da pasta de teste; publicação local não comprova sincronização.' 385 80 | Out-Null

    $page = New-Page
    New-Label $page 'Selecione uma rotina e use o botão para escolher sua pasta de destino. Nomes finais e contratos dos extratores são preservados.' 0 60 | Out-Null
    $script:destinations = New-Grid $page 70 350
    $destinations.Columns.Add('routine', 'Rotina') | Out-Null
    $destinations.Columns.Add('target', 'Arquivo de destino') | Out-Null
    $destinations.Columns[0].ReadOnly = $true
    $destinations.Columns[1].FillWeight = 220
    $destinationButton = New-Object Windows.Forms.Button
    $destinationButton.Text = 'Escolher pasta da rotina…'
    $destinationButton.Location = New-Object Drawing.Point(0, 440)
    $destinationButton.Width = 270
    $destinationButton.Add_Click({
        if ($null -eq $destinations.CurrentRow) { return }
        $row = $destinations.CurrentRow
        $picker = New-Object Windows.Forms.FolderBrowserDialog
        if (-not [string]$row.Cells[1].Value) { Show-NativeError (T 'Informe o nome completo do arquivo de destino na tabela antes de escolher a pasta.'); return }
        $picker.SelectedPath = Split-Path -Parent ([string]$row.Cells[1].Value)
        if ($picker.ShowDialog() -eq 'OK') {
            $name = Split-Path -Leaf ([string]$row.Cells[1].Value)
            $row.Cells[1].Value = Join-Path $picker.SelectedPath $name
        }
        $picker.Dispose()
    })
    $page.Controls.Add($destinationButton)
    $destinationAdd=New-Object Windows.Forms.Button
    $destinationAdd.Text='Adicionar script…';$destinationAdd.SetBounds(290,440,220,32)
    $destinationAdd.Add_Click({ Add-Routine })
    $page.Controls.Add($destinationAdd)
    $destinationRemove=New-Object Windows.Forms.Button
    $destinationRemove.Text='Retirar rotina…';$destinationRemove.SetBounds(530,440,220,32)
    $destinationRemove.Add_Click({
        if($null -eq $destinations.CurrentRow){return}
        Remove-Routine $destinations.CurrentRow.Index
    })
    $page.Controls.Add($destinationRemove)

    $page = New-Page
    New-Label $page 'Selecione a rotina e clique em Editar. Defina frequência, dias, vários horários e posição na fila. Diária executa até um sucesso por data; Todos os horários permite atualizar novamente. Somente dias úteis seleciona segunda a sexta.' 0 75 | Out-Null
    $script:routines = New-Grid $page 85 320
    $enabledColumn = New-Object Windows.Forms.DataGridViewCheckBoxColumn
    $enabledColumn.HeaderText = 'Ativa'; $routines.Columns.Add($enabledColumn) | Out-Null
    foreach($column in @('Rotina','Frequência','Horários próprios','Dias','Ordem')) { $routines.Columns.Add($column,$column) | Out-Null }
    $routines.ReadOnly=$true
    $routines.Add_CellDoubleClick({ param($sender,$e) Collect-Configuration; Edit-Routine $e.RowIndex })
    $routines.Height=230
    $editJob=New-Object Windows.Forms.Button
    $editJob.Text='Editar rotina'; $editJob.SetBounds(0,325,180,32)
    $editJob.Add_Click({ if($null -ne $routines.CurrentRow){Collect-Configuration; Edit-Routine $routines.CurrentRow.Index} })
    $page.Controls.Add($editJob)
    $addJob=New-Object Windows.Forms.Button
    $addJob.Text='Adicionar script…'; $addJob.SetBounds(200,325,220,32)
    $addJob.Add_Click({ Add-Routine })
    $page.Controls.Add($addJob)
    $removeJob=New-Object Windows.Forms.Button
    $removeJob.Text='Retirar rotina…'; $removeJob.SetBounds(440,325,220,32)
    $removeJob.Add_Click({
        if($null -eq $routines.CurrentRow){return}
        Remove-Routine $routines.CurrentRow.Index
    })
    $page.Controls.Add($removeJob)
    New-Label $page 'Monitor próprio: verifica os horários e atrasos com a interface fechada, enquanto este usuário estiver conectado ao Windows. Não é um serviço e não contorna SSO ou VPN.' 368 55 | Out-Null
    $script:schedules = New-Object Windows.Forms.CheckBox
    $schedules.Location = New-Object Drawing.Point(0, 425)
    $schedules.Size = New-Object Drawing.Size(880, 28)
    $schedules.Text = 'Instalar monitor próprio para executar horários com a interface fechada'
    $script:pauseSchedules=New-Object Windows.Forms.CheckBox
    $pauseSchedules.Text='Pausar agendamentos após instalar (opcional)'
    $pauseSchedules.SetBounds(0,465,880,28)
    $page.Controls.Add($pauseSchedules)
    $page.Controls.Add($schedules)

    $page = New-Page
    New-Label $page 'O pacote já inclui Python e dependências privados. O teste valida imports, SQLite, interface e contratos sem login, VPN ou extrações corporativas.' 0 70 | Out-Null
    $verifyButton = New-Object Windows.Forms.Button
    $verifyButton.Text = 'Verificar dependências offline'
    $verifyButton.Location = New-Object Drawing.Point(0, 80)
    $verifyButton.Width = 320
    $verifyButton.Add_Click({ Start-Operation 'health' })
    $page.Controls.Add($verifyButton)
    $healthBar=New-Object Windows.Forms.ProgressBar
    $healthBar.SetBounds(0,120,890,15); $healthBar.Style='Marquee'; $healthBar.Visible=$false
    $page.Controls.Add($healthBar)
    $script:dependenciesText = New-TextArea $page 150 330
    $dependenciesText.Text = 'O mesmo health check será obrigatório antes e depois da ativação. Falha externa de autenticação/VPN não é usada como critério de rollback.'

    $page = New-Page
    $script:review = New-TextArea $page 0 390
    $script:approve = New-Object Windows.Forms.CheckBox
    $approve.Location = New-Object Drawing.Point(0, 410)
    $approve.Size = New-Object Drawing.Size(870, 65)
    $approve.Text = 'Confirmo a instalação na pasta revisada. Criar backup e os atalhos deste aplicativo.'
    New-Label $page 'O monitor é opcional e só será instalado se selecionado na etapa de horários. A confirmação abaixo é obrigatória para aplicar as alterações. Cancelar preserva a instalação atual.' 395 55 | Out-Null
    $approve.Top=455
    $page.Controls.Add($approve)

    $page = New-Page
    $script:progress = New-Object Windows.Forms.ProgressBar
    $progress.Location = New-Object Drawing.Point(0, 0)
    $progress.Size = New-Object Drawing.Size(890, 22)
    $progress.Style = 'Marquee'
    $page.Controls.Add($progress)
    $script:log = New-TextArea $page 40 440

    $script:status = New-Object Windows.Forms.Label
    $status.Location = New-Object Drawing.Point(30, 635)
    $status.Size = New-Object Drawing.Size(900, 28)
    $status.Anchor = 'Bottom,Left,Right'
    $form.Controls.Add($status)
    $script:back = New-Object Windows.Forms.Button
    $back.Text = 'Voltar'; $back.Location = New-Object Drawing.Point(590, 672)
    $script:next = New-Object Windows.Forms.Button
    $next.Text = 'Avançar'; $next.Location = New-Object Drawing.Point(705, 672)
    $script:cancel = New-Object Windows.Forms.Button
    $cancel.Text = 'Cancelar'; $cancel.Location = New-Object Drawing.Point(820, 672)
    foreach ($control in @($back, $next, $cancel)) { $control.Size = New-Object Drawing.Size(105, 32); $control.Anchor = 'Bottom,Right'; $form.Controls.Add($control) }
    $operationControls = @($rootBox,$browse,$operation,$languageChoice,$email,$destinations,$destinationButton,$destinationAdd,$destinationRemove,$routines,$editJob,$addJob,$removeJob,$schedules,$pauseSchedules,$approve)

    function Translate-Controls($Parent) {
        foreach($c in $Parent.Controls) {
            if($c -is [Windows.Forms.Label] -or $c -is [Windows.Forms.Button] -or $c -is [Windows.Forms.CheckBox]) {
                if($null -eq $c.Tag){$c.Tag=$c.Text}
                $c.Text=T ([string]$c.Tag)
            }
            if($c -is [Windows.Forms.DataGridView]) {
                foreach($column in $c.Columns){if($null -eq $column.Tag){$column.Tag=$column.HeaderText}; $column.HeaderText=T ([string]$column.Tag)}
            }
        }
    }
    function Show-Page([int]$Index) {
        Update-PreviewSummary
        $form.Text = T 'CAIO • Instalação e atualização'
        $diagnostic.Text = T $diagnostic.Tag @($env:USERNAME,$env:COMPUTERNAME,$PSVersionTable.PSVersion,$ExecutionContext.SessionState.LanguageMode)

        $subtitle.Text = T 'TESTE ISOLADO • Versão {0} • Runtime privado • Versionamento interno' @($script:release.version)
        foreach ($panel in $script:pages) { $panel.Visible = $false }
        $script:pageIndex = $Index
        $script:pages[$Index].Visible = $true
        $title.Text = "$($Index + 1). $(T $script:titles[$Index])"
        $back.Enabled = $Index -gt 0 -and $Index -lt 7
        $next.Text = if ($Index -eq 6) { 'Instalar' } elseif ($Index -eq 7) { 'Abrir aplicativo' } else { 'Avançar' }
        $next.Enabled = $Index -lt 7 -or $script:completed
        $next.Text=T $next.Text; $back.Text=T 'Voltar'; $cancel.Text=T $(if($script:completed){'Fechar'}else{'Cancelar'})
        Translate-Controls $script:pages[$Index]
        $selectedOperation=$operation.SelectedIndex
        $operation.Items.Clear()
        $operation.Items.AddRange(@((T 'Instalar / atualizar'),(T 'Reparar instalação'),(T 'Abrir versão instalada')))
        $operation.SelectedIndex=$selectedOperation
        Set-NativeControlSizes $script:pages[$Index]
        if ($Index -eq 2) { $next.Enabled = Test-NativeEmail $email.Text }
        if($Index -eq 5 -and -not $script:healthPassed -and $null -eq $script:job){Start-Operation 'health'}
    }
    function Collect-Configuration {
        $destinations.EndEdit() | Out-Null
        $routines.EndEdit() | Out-Null
        $script:config.email = $email.Text.Trim()
        $script:config.install_schedules = $schedules.Checked
        $script:config.language = $script:language
        $script:config.scheduling_paused = $pauseSchedules.Checked
        for($index=0;$index -lt $destinations.Rows.Count;$index++) {
            $script:config.routines[$index].target=[string]$destinations.Rows[$index].Cells[1].Value
        }
    }
    function Fill-Configuration($Value) {
        $script:fillingConfiguration = $true
        $script:previewValue = $Value
        $script:config = $Value.config
        if(-not $script:languageChosen){$languageChoice.SelectedIndex=[Array]::IndexOf(@('pt-BR','en','es'),[string]$config.language)}
        $email.Text = [string]$config.email
        $schedules.Checked = [bool]$config.install_schedules
        $pauseSchedules.Checked=[bool]$config.scheduling_paused
        Refresh-RoutineRows
        $script:fillingConfiguration = $false
        Update-PreviewSummary
    }
    function Update-PreviewSummary {
        if ($null -eq $script:previewValue) { return }
        $current = if ($null -eq $script:previewValue.current) { 'não instalada' } else { [string]$script:previewValue.current.version }
        $locationStatus.Text = T "Versão atual: {0}`r`nNova versão: {1}`r`nDestino: {2}`r`nDados, configurações, scripts adicionais e último sucesso são preservados nas atualizações." @((T $current),$release.version,$rootBox.Text)
        $identityLabels = @{ user='Usuário'; computer='Computador'; home='Pasta pessoal' }
        $lines = @(
            foreach ($property in $script:previewValue.identity.PSObject.Properties) {
                $caption = if ($identityLabels.ContainsKey($property.Name)) { $identityLabels[$property.Name] } else { $property.Name }
                (T $caption) + ': ' + [string]$property.Value
            }
        )
        $accounts = @($script:previewValue.onedrives | ForEach-Object { (T ([string]$_.kind)) + ' • ' + [string]$_.account + ' • ' + [string]$_.path })
        if (-not $accounts.Count) { $accounts = @((T 'Nenhuma conta detectada')) }
        $identityText.Text = ($lines -join "`r`n") + "`r`n`r`nOneDrive:`r`n" + ($accounts -join "`r`n")
    }

    function Start-Operation([string]$Action) {
        if ($null -ne $script:job) { return }
        $script:jobAction = $Action
        $log.Clear()
        $request = @{ action = $Action; data_root = $rootBox.Text.Trim(); payload = $script:payload }
        if ($Action -in @('install', 'repair', 'update','add_script')) { $request.config = $script:config }
        if ($Action -eq 'add_script') { $request.script=$script:addScript }
        if ($Action -eq 'rollback') { $request.backup = $Backup }
        $script:job = Start-NativeBridge $script:payload $request
        foreach ($control in $operationControls) { $control.Enabled = $false }
        $back.Enabled = $false; $next.Enabled = $false; $verifyButton.Enabled = $false
        $status.Text = T 'Processando… acompanhe o log acima.'
        if($Action -eq 'health'){$healthBar.Visible=$true; $dependenciesText.Text=T 'Validando integridade e dependências…'}
    }

    $back.Add_Click({ Show-Page ($script:pageIndex - 1) })
    $next.Add_Click({
        try {
            if ($script:pageIndex -eq 7) { Open-NativeApplication $rootBox.Text; $script:exitCode = 0; $form.Close(); return }
            if ($script:pageIndex -eq 1) { Start-Operation 'preview'; return }
            if ($script:pageIndex -eq 2) {
                if (-not (Test-NativeEmail $email.Text)) {
                    $email.Focus() | Out-Null
                    throw (T 'Informe um e-mail válido para continuar.')
                }
                Collect-Configuration
            }
            if ($script:pageIndex -eq 5) {
                Collect-Configuration
                $review.Text = (T "Versão nova: {0}`r`nPasta: {1}`r`nBackup: backups\app (verificação SHA-256 obrigatória)`r`nHealth check offline antes/depois; ativação por ponteiro; rollback automático em falha interna.`r`n`r`n" @($release.version,$rootBox.Text)) + ($script:config | ConvertTo-Json -Depth 64)
            }
            if ($script:pageIndex -eq 6) {
                if (-not $approve.Checked) { throw 'Revise e marque a aplicação das alterações.' }
                Show-Page 7
                $action = if ($operation.SelectedIndex -eq 1) { 'repair' } else { 'install' }
                Start-Operation $action
                return
            }
            Show-Page ($script:pageIndex + 1)
        } catch { Show-NativeError $_.Exception.Message }
    })
    $cancel.Add_Click({
        if ($null -ne $script:job) {
            [IO.File]::WriteAllText($script:job.Cancel, 'cancel')
            $script:cancelPending = $true
            $status.Text = T 'Cancelamento solicitado; aguardando checkpoint e reversão segura.'
            $cancel.Enabled = $false
        } else { $form.Close() }
    })
    $form.Add_FormClosing({
        param($sender, $eventArgs)
        if ($null -ne $script:job) {
            [IO.File]::WriteAllText($script:job.Cancel, 'cancel')
            $script:cancelPending = $true
            $eventArgs.Cancel = $true
        }
    })
    $script:timer = New-Object Windows.Forms.Timer
    $timer.Interval = 400
    $timer.Add_Tick({
        if ($null -eq $script:job) { return }
        try {
            if (Test-Path -LiteralPath $script:job.Events) {
                $lines = @(Get-Content -LiteralPath $script:job.Events -Encoding UTF8 | Select-Object -Last 200)
                $messages = foreach ($line in $lines) { try { (ConvertFrom-Json $line).stage } catch { } }
                $log.Text = ($messages | ForEach-Object {T $_}) -join "`r`n"
                if($script:jobAction -eq 'health'){$dependenciesText.Text=$log.Text}
            }
            if (-not $script:job.Process.HasExited) { return }
            $ended = $script:job
            $script:job = $null
            foreach ($control in $operationControls) { $control.Enabled = $true }
            try { $value = Get-NativeBridgeResult $ended } finally { $ended.Process.Dispose() }
            $verifyButton.Enabled = $true
            $cancel.Enabled = $true
            $status.Text = T 'Etapa anterior concluída com sucesso.'
            $healthBar.Visible=$false
            if ($script:jobAction -eq 'preview') {
                Fill-Configuration $value
                if ($script:cancelPending) { $form.Close(); return }
                if ($operation.SelectedIndex -eq 2) { Open-NativeApplication $rootBox.Text; $script:exitCode = 0; $form.Close(); return }
                if ($AutoUpdate) {
                    Show-Page 7
                    $action = if ($Backup) { 'rollback' } else { 'update' }
                    Start-Operation $action
                } else { Show-Page 2 }
            } elseif ($script:jobAction -eq 'add_script') {
                $script:config=$value.config
                Refresh-RoutineRows
                Show-Page $script:addScriptPage
                Edit-Routine ($script:config.routines.Count-1)
            } elseif ($script:jobAction -eq 'health') {
                $script:healthPassed=$true
                $dependenciesText.AppendText("`r`n" + (T 'Etapa anterior concluída com sucesso.') + "`r`n" + ($value | ConvertTo-Json -Depth 10))
                Show-Page 5
            } else {
                $script:completed = $true
                $script:exitCode = 0
                $progress.Style = 'Continuous'; $progress.Value = 100
                $cancel.Text = T 'Fechar'
                $next.Enabled = $true
                if ($AutoUpdate) { Open-NativeApplication $rootBox.Text; $form.Close() }
            }
        } catch {
            $script:job = $null
            $script:exitCode = 2
            $displayError = T $_.Exception.Message
            $status.Text = $displayError
            if (-not $log.Text.EndsWith($displayError)) { $log.AppendText("`r`n" + $displayError) }
            $verifyButton.Enabled = $true; $cancel.Enabled = $true
            $back.Enabled = $script:pageIndex -gt 0 -and $script:pageIndex -lt 7
            if ($script:pageIndex -lt 7) { $next.Enabled = $true }
            $progress.Style = 'Continuous'; $progress.Value = 0
            $healthBar.Visible=$false
            if($script:pageIndex -eq 5){$dependenciesText.AppendText("`r`n" + $displayError); $next.Enabled=$false}
            Show-NativeError $_.Exception.Message
            if ($AutoUpdate -and (Test-Path -LiteralPath (Join-Path $rootBox.Text 'installation.json'))) { Open-NativeApplication $rootBox.Text; $form.Close() }
        }
    })
    $next.Name = 'primary'
    $destinationRemove.Name = 'danger'
    $removeJob.Name = 'danger'
    Set-NativeTheme $form
    $title.ForeColor = Get-NativeThemeColor 'firstLevelElements'
    $subtitle.ForeColor = Get-NativeThemeColor 'foregroundNeutralSecondary'
    Set-NativeControlSizes $form
    $form.ResumeLayout($true)
    $form.Add_Load({ Fit-NativeWindow $form })
    $form.Add_Shown({ if ($AutoUpdate) { Show-Page 1; Start-Operation 'preview' } })
    Show-Page 0
    $timer.Start()
    [void]$form.ShowDialog()
    $timer.Stop(); $timer.Dispose()
    if ($null -ne $brand.Image) { $brand.Image.Dispose() }
    $form.Dispose()
    exit $script:exitCode
} catch {
    [Windows.Forms.MessageBox]::Show((T $_.Exception.Message), (T 'Orquestrador • instalação não iniciada')) | Out-Null
    exit 2
}
