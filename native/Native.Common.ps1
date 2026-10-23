Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-NativeEmail([string]$Value) {
    $value = $Value.Trim()
    if ($value -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { return $false }
    try { return (New-Object Net.Mail.MailAddress($value)).Address -eq $value } catch { return $false }
}

# Use the actual font metrics, including after DPI scaling and translation.
function Set-NativeControlSizes($Parent) {
    foreach ($control in $Parent.Controls) {
        if (($control -is [Windows.Forms.TextBox] -and -not $control.Multiline) -or
            $control -is [Windows.Forms.ComboBox] -or $control -is [Windows.Forms.DateTimePicker] -or
            $control -is [Windows.Forms.Button] -or $control -is [Windows.Forms.CheckBox]) {
            $height = [Math]::Max(36, [Math]::Max($control.Font.Height + 14, $control.PreferredSize.Height))
            if ($control -is [Windows.Forms.TextBox]) { $control.AutoSize = $false }
            $control.MinimumSize = New-Object Drawing.Size($control.MinimumSize.Width, $height)
            $control.Height = [Math]::Max($control.Height, $height)
        }
        Set-NativeControlSizes $control
    }
}

function Fit-NativeWindow($Window) {
    $area = [Windows.Forms.Screen]::FromControl($Window).WorkingArea
    $width = [Math]::Min($Window.Width, $area.Width - 24)
    $height = [Math]::Min($Window.Height, $area.Height - 24)
    $Window.MinimumSize = New-Object Drawing.Size([Math]::Min($Window.MinimumSize.Width,$width),[Math]::Min($Window.MinimumSize.Height,$height))
    $Window.Size = New-Object Drawing.Size($width,$height)
}

function Read-NativeJson([string]$Path) {
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

# Both desktop interfaces consume the complete user-provided theme JSON.
function Get-NativeThemeColor([string]$Name) {
    return [Drawing.ColorTranslator]::FromHtml([string]$script:visualTheme.$Name)
}

function Set-NativeTheme($Parent) {
    $Parent.ForeColor = Get-NativeThemeColor 'foreground'
    $Parent.BackColor = Get-NativeThemeColor 'backgroundNeutral'
    foreach ($control in $Parent.Controls) {
        Set-NativeTheme $control
        if ($control -is [Windows.Forms.Button]) {
            $control.FlatStyle = 'Flat'
            $control.FlatAppearance.BorderColor = Get-NativeThemeColor 'shapeStroke'
            $control.FlatAppearance.MouseOverBackColor = Get-NativeThemeColor 'backgroundDark'
            $control.FlatAppearance.MouseDownBackColor = Get-NativeThemeColor 'backgroundDark'
            $control.BackColor = Get-NativeThemeColor 'background'
            $control.ForeColor = Get-NativeThemeColor 'accent'
            if ($control.Name -eq 'primary') {
                $control.BackColor = Get-NativeThemeColor 'accent'
                $control.ForeColor = Get-NativeThemeColor 'foregroundButton'
                $control.FlatAppearance.MouseOverBackColor = Get-NativeThemeColor 'firstLevelElements'
                $control.FlatAppearance.MouseDownBackColor = Get-NativeThemeColor 'firstLevelElements'
            } elseif ($control.Name -eq 'danger') {
                $control.ForeColor = Get-NativeThemeColor 'bad'
                $control.FlatAppearance.BorderColor = Get-NativeThemeColor 'bad'
            }
        } elseif ($control -is [Windows.Forms.TextBox] -or $control -is [Windows.Forms.ComboBox] -or $control -is [Windows.Forms.ListBox]) {
            $control.BackColor = Get-NativeThemeColor 'background'
        } elseif ($control -is [Windows.Forms.DataGridView]) {
            $control.EnableHeadersVisualStyles = $false
            $control.BackgroundColor = Get-NativeThemeColor 'background'
            $control.GridColor = Get-NativeThemeColor 'shapeStroke'
            $control.ColumnHeadersDefaultCellStyle.BackColor = Get-NativeThemeColor 'tableAccent'
            $control.ColumnHeadersDefaultCellStyle.ForeColor = Get-NativeThemeColor 'foregroundLight'
            $control.DefaultCellStyle.BackColor = Get-NativeThemeColor 'background'
            $control.DefaultCellStyle.ForeColor = Get-NativeThemeColor 'foreground'
            $control.DefaultCellStyle.SelectionBackColor = Get-NativeThemeColor 'accent'
            $control.DefaultCellStyle.SelectionForeColor = Get-NativeThemeColor 'foregroundSelected'
            $control.AlternatingRowsDefaultCellStyle.BackColor = [Drawing.ColorTranslator]::FromHtml([string]$script:visualTheme.visualStyles.tableEx.'*'.values[0].backColorSecondary.solid.color)
        }
    }
}

function Write-NativeJson([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 64), (New-Object Text.UTF8Encoding($false)))
    if ([IO.File]::Exists($Path)) {
        $previous = $temporary + '.previous'
        [IO.File]::Replace($temporary, $Path, $previous)
        [IO.File]::Delete($previous)
    } else {
        [IO.File]::Move($temporary, $Path)
    }
}

function Quote-NativeArgument([string]$Value) {
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Start-HiddenProcess([string]$File, [string[]]$Arguments, [string]$WorkingDirectory) {
    if (-not [IO.File]::Exists($File)) { throw "Componente ausente: $File" }
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $File
    $info.Arguments = (($Arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' ')
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $info.WorkingDirectory = $WorkingDirectory
    return [Diagnostics.Process]::Start($info)
}

function Start-NativeBridge([string]$Payload, $Request) {
    $work = Join-Path $env:LOCALAPPDATA ('Orquestrador-Teste\bootstrap\' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($work) | Out-Null
    $requestPath = Join-Path $work 'request.json'
    $resultPath = Join-Path $work 'result.json'
    $eventsPath = Join-Path $work 'events.jsonl'
    $cancelPath = Join-Path $work 'cancel.request'
    Write-NativeJson $requestPath $Request
    $runtime = Join-Path $Payload 'runtime\pythonw.exe'
    $arguments = @('-B', '-m', 'orquestrador_app.native_bridge', '--request', $requestPath, '--result', $resultPath, '--events', $eventsPath, '--cancel', $cancelPath)
    $process = Start-HiddenProcess $runtime $arguments (Join-Path $Payload 'src')
    return [pscustomobject]@{ Process = $process; Result = $resultPath; Events = $eventsPath; Cancel = $cancelPath; Work = $work; Started = [DateTime]::UtcNow }
}

function Get-NativeBridgeResult($Job) {
    if (-not $Job.Process.HasExited) { throw 'A operação ainda está em execução.' }
    if (-not [IO.File]::Exists($Job.Result)) {
        throw "O runtime não retornou diagnóstico (código $($Job.Process.ExitCode)). Verifique bloqueios de execução e dependências. Registro: $($Job.Work)"
    }
    $result = Read-NativeJson $Job.Result
    if (-not $result.ok) { throw $result.error }
    if ($Job.Process.ExitCode -ne 0) { throw "Processo terminou com código $($Job.Process.ExitCode)." }
    return $result.result
}

function Wait-OwnedParent([int]$OwnerPid, [double]$OwnerStarted, [int]$TimeoutSeconds = 120) {
    if ($OwnerPid -le 0) { return }
    $process = Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue
    if ($null -eq $process) { return }
    $epoch = [DateTime]::SpecifyKind([DateTime]'1970-01-01', [DateTimeKind]::Utc)
    $actual = ($process.StartTime.ToUniversalTime() - $epoch).TotalSeconds
    if ([Math]::Abs($actual - $OwnerStarted) -gt 1.0) {
        throw 'O identificador do processo foi reutilizado. Nenhum processo foi encerrado.'
    }
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        throw 'O aplicativo não encerrou no prazo. Atualização cancelada; nenhum processo foi forçado a fechar.'
    }
}

function Get-NativePayload([string]$PackageRoot, [string]$ScriptDirectory) {
    if ($PackageRoot) {
        $candidate = Join-Path $PackageRoot 'payload'
    } elseif (Test-Path -LiteralPath (Join-Path $ScriptDirectory 'payload\release.json')) {
        $candidate = Join-Path $ScriptDirectory 'payload'
    } else {
        $candidate = Split-Path -Parent $ScriptDirectory
    }
    if (-not (Test-Path -LiteralPath (Join-Path $candidate 'release.json'))) {
        throw 'Extraia o ZIP completo antes de abrir o instalador. O payload não foi encontrado.'
    }
    return [IO.Path]::GetFullPath($candidate)
}

function Open-NativeApplication([string]$DataRoot) {
    $current = Read-NativeJson (Join-Path $DataRoot 'installation.json')
    if (($current.PSObject.Properties.Name -contains 'distribution') -and $current.distribution -eq 'native-scripts') {
        $launcher = Join-Path $DataRoot 'launch\Iniciar.vbs'
        $hostPath = Join-Path $env:WINDIR 'System32\wscript.exe'
        Start-HiddenProcess $hostPath @('//Nologo', $launcher) $DataRoot | Out-Null
    } elseif ($current.owner -eq 'orquestrador-app-v1') {
        # A rollback may restore the preceding test edition, distributed as EXE.
        $executable = [IO.Path]::GetFullPath([string]$current.executable)
        $managed = [IO.Path]::GetFullPath((Join-Path $DataRoot 'app')) + [IO.Path]::DirectorySeparatorChar
        if (-not $executable.StartsWith($managed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Versão anterior fora da pasta gerenciada.' }
        Start-HiddenProcess $executable @('--data-root', $DataRoot) $DataRoot | Out-Null
    } else { throw 'Instalação não reconhecida para abertura.' }
}

function Show-NativeError([string]$Message) {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($Message, 'Orquestrador', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Error) | Out-Null
}
