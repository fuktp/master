[CmdletBinding()]
param(
    [Parameter()]
    [string]$ConfigPath = "",

    [Parameter()]
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$TaskPrefix = "Pipefy_Orquestrador",

    [Parameter()]
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$ScriptPath = [string]$MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    throw "Não foi possível identificar o caminho do instalador."
}
$ScriptRoot = Split-Path -Parent $ScriptPath
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path -Path $ScriptRoot -ChildPath "pipefy_orchestrator.config.json"
}
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$PackageRoot = Split-Path -Parent $ConfigPath
$OrchestratorPath = Join-Path $PackageRoot "pipefy_orchestrator.py"

if (-not (Test-Path -LiteralPath $OrchestratorPath -PathType Leaf)) {
    throw "Orquestrador não encontrado: $OrchestratorPath"
}

$Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$ExistingTasks = @(Get-ScheduledTask -TaskName "$TaskPrefix-*" -ErrorAction SilentlyContinue)

if ($Remove) {
    foreach ($Task in $ExistingTasks) {
        Unregister-ScheduledTask -TaskName $Task.TaskName -Confirm:$false
        Write-Host "Tarefa removida: $($Task.TaskName)"
    }
    if ($ExistingTasks.Count -eq 0) {
        Write-Host "Nenhuma tarefa encontrada com o prefixo $TaskPrefix."
    }
    exit 0
}

if (-not $Config.schedules -or $Config.schedules.Count -eq 0) {
    throw "Nenhum horário definido em schedules."
}

$PythonCommand = [string]$Config.python_executable
$Python = Get-Command $PythonCommand -ErrorAction Stop
$PythonPath = $Python.Source

& $PythonPath $OrchestratorPath --config $ConfigPath configure-schedules --if-needed
if ($LASTEXITCODE -ne 0) {
    throw "Configuração das frequências cancelada ou inválida. Nenhuma tarefa foi instalada."
}
$Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

$ProjectRootValue = [string]$Config.project_root
if ([System.IO.Path]::IsPathRooted($ProjectRootValue)) {
    $ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRootValue)
}
else {
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PackageRoot $ProjectRootValue))
}

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Diretório do projeto não encontrado: $ProjectRoot"
}

$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentIdentity `
    -LogonType Interactive `
    -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

$DesiredTaskNames = @()
foreach ($Schedule in $Config.schedules) {
    $TimeText = [string]$Schedule
    $ParsedTime = [datetime]::ParseExact(
        $TimeText,
        "HH:mm",
        [System.Globalization.CultureInfo]::InvariantCulture
    )
    $TaskName = "$TaskPrefix-$($TimeText.Replace(':', ''))"
    $DesiredTaskNames += $TaskName
    $Arguments = '"{0}" --config "{1}" run' -f $OrchestratorPath, $ConfigPath
    $Action = New-ScheduledTaskAction `
        -Execute $PythonPath `
        -Argument $Arguments `
        -WorkingDirectory $ProjectRoot
    $Trigger = New-ScheduledTaskTrigger -Daily -At $ParsedTime
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Extrações Pipefy e KWMS com frequência diária/semanal por rotina." `
        -Force | Out-Null
    Write-Host "Tarefa instalada: $TaskName às $TimeText"
}

foreach ($Task in $ExistingTasks) {
    if ($Task.TaskName -notin $DesiredTaskNames) {
        Unregister-ScheduledTask -TaskName $Task.TaskName -Confirm:$false
        Write-Host "Tarefa obsoleta removida: $($Task.TaskName)"
    }
}

Write-Host "Instalação concluída. As tarefas executam somente com o usuário conectado."
