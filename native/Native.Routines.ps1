# Shared actions are called directly; hidden-page buttons cannot PerformClick.
function Add-Routine {
    if ($null -ne $script:job) { return }
    $picker = New-Object Windows.Forms.OpenFileDialog
    $picker.Filter = 'Python (*.py)|*.py'
    try {
        if ($picker.ShowDialog($form) -eq 'OK') {
            Collect-Configuration
            $script:addScript = $picker.FileName
            $script:addScriptPage = $script:pageIndex
            Start-Operation 'add_script'
        }
    } finally { $picker.Dispose() }
}

function Remove-Routine([int]$Index) {
    if ($null -ne $script:job -or $Index -lt 0 -or $Index -ge $script:config.routines.Count) { return }
    Collect-Configuration
    $id = $script:config.routines[$Index].id
    $dependents = @($script:config.routines | Where-Object { @($_.dependencies | Where-Object { $_.job -ceq $id }).Count -gt 0 })
    if ($dependents.Count -gt 0) { Show-NativeError (T 'Retire as dependências desta rotina antes de removê-la.'); return }
    $message = (T 'Retirar esta rotina do programa?') + "`r`n" + (T 'O arquivo original, o histórico e as versões serão preservados.')
    if ([Windows.Forms.MessageBox]::Show($form, $message, 'CAIO', 'YesNo', 'Question', 'Button2') -ne 'Yes') { return }
    $script:config.routines = @($script:config.routines | Where-Object { $_.id -cne $id })
    $position = 0
    foreach ($routine in @($script:config.routines | Sort-Object order,id)) { $routine.order = $position; $position++ }
    Refresh-RoutineRows
}

function Get-NativeDayPreset([string]$Frequency, [int]$Weekday = 0) {
    if ($Frequency -eq 'weekdays') { return 0..4 }
    if ($Frequency -eq 'weekly') { return $Weekday }
    return 0..6
}

function Test-NativeDayPreset([string]$Frequency, [int[]]$Days, [int]$Weekday = 0) {
    if ($Frequency -eq 'weekly' -and $Days.Count -eq 1) { $Weekday = $Days[0] }
    return (($Days | Sort-Object -Unique) -join ',') -eq ((Get-NativeDayPreset $Frequency $Weekday) -join ',')
}

function Edit-Routine([int]$Index) {
    if ($Index -lt 0 -or $null -eq $script:config -or $Index -ge $script:config.routines.Count) { return }
    $routine = $script:config.routines[$Index]
    $dialog = New-Object Windows.Forms.Form
    $dialog.SuspendLayout()
    $dialog.AutoScaleDimensions = New-Object Drawing.SizeF(96,96)
    $dialog.AutoScaleMode = 'Dpi'
    $dialog.Text = (T 'Editar rotina') + ' - ' + $routine.label
    $dialog.Size = New-Object Drawing.Size(850,760)
    $dialog.MinimumSize = New-Object Drawing.Size(760,680)
    $dialog.StartPosition = 'CenterParent'
    $dialog.Font = $form.Font
    $dialog.Icon = $form.Icon
    $dialog.BackColor = Get-NativeThemeColor 'backgroundNeutral'
    $dialog.ForeColor = Get-NativeThemeColor 'foreground'
    $tip = New-Object Windows.Forms.ToolTip
    $scroll = New-Object Windows.Forms.Panel
    $scroll.Dock = 'Fill'; $scroll.AutoScroll = $true
    $dialog.Controls.Add($scroll)
    $fields = New-Object Windows.Forms.TableLayoutPanel
    $fields.Dock = 'Top'; $fields.AutoSize = $true
    $fields.Padding = New-Object Windows.Forms.Padding(16)
    $fields.ColumnCount = 2; $fields.RowCount = 0
    $fields.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Absolute',190))) | Out-Null
    $fields.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent',100))) | Out-Null
    $scroll.Controls.Add($fields)
    function Add-EditorRow([string]$Text, $Control) {
        $row = $fields.RowCount; $fields.RowCount++
        $fields.RowStyles.Add((New-Object Windows.Forms.RowStyle('AutoSize'))) | Out-Null
        $Control.Dock = 'Fill'
        $Control.AccessibleName = T $Text
        $Control.Name = $Text
        $Control.Margin = New-Object Windows.Forms.Padding(4,6,4,6)
        if ($Text) {
            $label = New-Object Windows.Forms.Label
            $label.Text = T $Text; $label.AutoSize = $true
            $label.MaximumSize = New-Object Drawing.Size(180,0)
            $label.Margin = New-Object Windows.Forms.Padding(0,12,8,6)
            $fields.Controls.Add($label,0,$row)
            $fields.Controls.Add($Control,1,$row)
        } else {
            $fields.Controls.Add($Control,0,$row)
            $fields.SetColumnSpan($Control,2)
        }
    }
    $frequency = New-Object Windows.Forms.ComboBox
    $frequency.DropDownStyle = 'DropDownList'
    $frequency.Items.AddRange(@((T 'Diária: um sucesso por data'),(T 'Semanal: um sucesso por semana'),(T 'Todos os horários: um sucesso por ocorrência'),(T 'Somente dias úteis: um sucesso por dia de segunda a sexta')))
    $codes = @('daily','weekly','every_run','weekdays')
    $frequency.SelectedIndex = [Array]::IndexOf($codes,[string]$routine.schedule.frequency)
    Add-EditorRow 'Frequência' $frequency
    $dayField = New-Object Windows.Forms.FlowLayoutPanel
    $dayField.FlowDirection = 'TopDown'; $dayField.WrapContents = $false; $dayField.AutoSize = $true
    $dayPattern = New-Object Windows.Forms.ComboBox
    $dayPattern.DropDownStyle = 'DropDownList'; $dayPattern.Width = 400
    $dayPattern.Items.AddRange(@((T 'Padrão da frequência'),(T 'Personalizado')))
    $dayField.Controls.Add($dayPattern)
    $dayButtons = New-Object Windows.Forms.FlowLayoutPanel
    $dayButtons.AutoSize = $true; $dayButtons.WrapContents = $false
    $dayField.Controls.Add($dayButtons)
    $days = @()
    $names = @('Segunda-feira','Terça-feira','Quarta-feira','Quinta-feira','Sexta-feira','Sábado','Domingo')
    for ($i=0;$i -lt 7;$i++) {
        $day = New-Object Windows.Forms.CheckBox
        $day.Appearance = 'Button'; $day.TextAlign = 'MiddleCenter'
        $name = T $names[$i]
        $day.Text = $name.Substring(0,1); $day.AccessibleName = $name
        $tip.SetToolTip($day,$name)
        $day.Size = New-Object Drawing.Size(48,38)
        $day.Checked = $routine.schedule.days -contains $i
        $dayButtons.Controls.Add($day); $days += $day
    }
    Add-EditorRow 'Dias da semana' $dayField
    $syncDays = @{ active = $false }
    $refreshPattern = {
        if ($syncDays.active) { return }
        $chosen = @(for ($i=0;$i -lt 7;$i++) { if ($days[$i].Checked) { $i } })
        $syncDays.active = $true
        $dayPattern.SelectedIndex = if (Test-NativeDayPreset $codes[$frequency.SelectedIndex] $chosen) { 0 } else { 1 }
        $syncDays.active = $false
    }
    $applyPreset = {
        if ($syncDays.active) { return }
        $syncDays.active = $true
        $preset = @(Get-NativeDayPreset $codes[$frequency.SelectedIndex] $routine.schedule.weekday)
        for ($i=0;$i -lt 7;$i++) { $days[$i].Checked = $preset -contains $i }
        $syncDays.active = $false
        & $refreshPattern
    }
    foreach ($day in $days) { $day.Add_CheckedChanged($refreshPattern) }
    $frequency.Add_SelectedIndexChanged($applyPreset)
    $dayPattern.Add_SelectedIndexChanged({ if ($dayPattern.SelectedIndex -eq 0) { & $applyPreset } })
    & $refreshPattern
    $calendarHelp = New-Object Windows.Forms.Label
    $calendarHelp.AutoSize = $true; $calendarHelp.MaximumSize = New-Object Drawing.Size(750,0)
    $calendarHelp.Text = T 'Diária e Todos os horários usam os sete dias; Somente dias úteis usa segunda a sexta; Semanal usa um dia inicial. Personalizado preserva os dias escolhidos sem mudar a regra de sucesso da frequência. Somente dias úteis ignora fins de semana.'
    Add-EditorRow '' $calendarHelp
    $timesField = New-Object Windows.Forms.TableLayoutPanel
    $timesField.AutoSize = $true; $timesField.ColumnCount = 2
    $timesField.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent',50))) | Out-Null
    $timesField.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent',50))) | Out-Null
    $times = New-Object Windows.Forms.ListBox
    $times.Dock = 'Fill'; $times.Height = 140; $times.IntegralHeight = $false
    $times.Items.AddRange([object[]]$routine.schedule.times); $times.Sorted = $true
    $timesField.Controls.Add($times,0,0)
    $tools = New-Object Windows.Forms.FlowLayoutPanel
    $tools.AutoSize = $true; $tools.FlowDirection = 'TopDown'; $tools.WrapContents = $false
    $clock = New-Object Windows.Forms.DateTimePicker
    $clock.Format = 'Custom'; $clock.CustomFormat = 'HH:mm'; $clock.ShowUpDown = $true; $clock.Width = 160
    $tip.SetToolTip($clock,(T 'Escolha a hora e os minutos; depois clique em Adicionar horário.'))
    $tools.Controls.Add($clock)
    $add = New-Object Windows.Forms.Button
    $add.Text = T 'Adicionar horário'; $add.AutoSize = $true
    $add.Add_Click({ $value=$clock.Value.ToString('HH:mm'); if (-not $times.Items.Contains($value)) { $times.Items.Add($value) | Out-Null } })
    $tools.Controls.Add($add)
    $remove = New-Object Windows.Forms.Button
    $remove.Text = T 'Retirar horário'; $remove.AutoSize = $true
    $remove.Add_Click({ if ($times.SelectedIndex -ge 0) { $times.Items.RemoveAt($times.SelectedIndex) } })
    $tools.Controls.Add($remove)
    $timesField.Controls.Add($tools,1,0)
    Add-EditorRow 'Horários próprios' $timesField
    $order = New-Object Windows.Forms.ComboBox
    $order.DropDownStyle = 'DropDownList'
    $ordered = @($script:config.routines | Sort-Object order,id)
    for ($i=1;$i -le $ordered.Count;$i++) { $order.Items.Add([string]$i) | Out-Null }
    $order.SelectedIndex = [Array]::IndexOf($ordered,$routine)
    Add-EditorRow 'Ordem na fila' $order
    $scriptPath = New-Object Windows.Forms.TextBox
    $scriptPath.Text = $routine.script
    Add-EditorRow 'Script Python' $scriptPath
    $version = New-Object Windows.Forms.TextBox
    $version.Text = $routine.script_version
    Add-EditorRow 'Versão do script' $version
    $commandBox = New-Object Windows.Forms.TextBox
    $commandBox.Text = $routine.command
    Add-EditorRow 'Subcomando do script' $commandBox
    $enabled = New-Object Windows.Forms.CheckBox
    $enabled.Text = T 'Habilitar esta rotina'; $enabled.Checked = $routine.enabled; $enabled.AutoSize = $true
    Add-EditorRow '' $enabled
    $browser = New-Object Windows.Forms.CheckBox
    $browser.Text = T 'Este script utiliza o navegador Edge'; $browser.Checked = $routine.requires_browser; $browser.AutoSize = $true
    Add-EditorRow '' $browser
    $help = New-Object Windows.Forms.Label
    $help.Text = T 'Semanal começa no primeiro dia selecionado. Dias extras recuperam pendências. Alterar a ordem reorganiza as demais posições automaticamente.'
    $help.AutoSize = $true; $help.MaximumSize = New-Object Drawing.Size(750,0)
    Add-EditorRow '' $help
    $buttons = New-Object Windows.Forms.FlowLayoutPanel
    $buttons.Dock = 'Bottom'; $buttons.FlowDirection = 'RightToLeft'; $buttons.AutoSize = $true
    $buttons.Padding = New-Object Windows.Forms.Padding(12)
    $dialog.Controls.Add($buttons)
    $cancelEdit = New-Object Windows.Forms.Button
    $cancelEdit.Text = T 'Cancelar'; $cancelEdit.AutoSize = $true; $cancelEdit.DialogResult = 'Cancel'
    $buttons.Controls.Add($cancelEdit); $dialog.CancelButton = $cancelEdit
    $ok = New-Object Windows.Forms.Button
    $ok.Text = T 'Salvar'; $ok.AutoSize = $true
    $ok.Add_Click({
        $chosen = @(for ($i=0;$i -lt 7;$i++) { if ($days[$i].Checked) { $i } })
        if ($chosen.Count -eq 0 -or $times.Items.Count -eq 0) { Show-NativeError (T 'Selecione ao menos um dia e um horário.'); return }
        $routine.schedule.frequency = $codes[$frequency.SelectedIndex]
        $routine.schedule.days = $chosen; $routine.schedule.weekday = $chosen[0]
        $routine.schedule.times = @($times.Items | ForEach-Object { [string]$_ })
        $routine.script = $scriptPath.Text.Trim(); $routine.script_version = $version.Text.Trim()
        $routine.command = $commandBox.Text.Trim(); $routine.requires_browser = $browser.Checked; $routine.enabled = $enabled.Checked
        $others = New-Object 'Collections.Generic.List[object]'
        foreach ($r in $ordered) { if ($r.id -cne $routine.id) { $others.Add($r) } }
        $others.Insert($order.SelectedIndex,$routine)
        for ($i=0;$i -lt $others.Count;$i++) { $others[$i].order = $i }
        $dialog.DialogResult = 'OK'; $dialog.Close()
    })
    $buttons.Controls.Add($ok); $dialog.AcceptButton = $ok
    $ok.Name = 'primary'
    Set-NativeTheme $dialog
    Set-NativeControlSizes $dialog
    $dialog.ResumeLayout($true)
    $dialog.Add_Load({ Fit-NativeWindow $dialog })
    try { [void]$dialog.ShowDialog($form) } finally { $tip.Dispose(); $dialog.Dispose() }
    Refresh-RoutineRows
}

function Refresh-RoutineRows {
    $routines.Rows.Clear()
    $destinations.Rows.Clear()
    foreach ($routine in $script:config.routines) {
        $dayNames = @('Seg','Ter','Qua','Qui','Sex','Sáb','Dom')
        $daysText = @($routine.schedule.days | ForEach-Object { T $dayNames[[int]$_] }) -join ', '
        if (-not (Test-NativeDayPreset $routine.schedule.frequency $routine.schedule.days $routine.schedule.weekday)) {
            $daysText = (T 'Personalizado') + ': ' + $daysText
        }
        $routines.Rows.Add([object[]]@([bool]$routine.enabled, [string]$routine.label, [string]$routine.schedule.frequency, ($routine.schedule.times -join ', '), $daysText, ([int]$routine.order+1))) | Out-Null
        $destinations.Rows.Add([object[]]@([string]$routine.label,[string]$routine.target)) | Out-Null
    }
}
