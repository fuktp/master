param([ValidateSet('open','uninstall')][string]$Action = 'open', [string]$DataRoot = '', [int]$ParentPid = 0, [double]$ParentStarted = 0)
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'Native.Common.ps1')
    Wait-OwnedParent $ParentPid $ParentStarted
    if (-not $DataRoot) {
        $locatorPath = Join-Path $env:LOCALAPPDATA 'Orquestrador-Teste\ultima-instalacao.json'
        if (-not (Test-Path -LiteralPath $locatorPath)) { throw 'Instalacao nao encontrada. Abra 01 - Instalar.vbs primeiro.' }
        $locator = Read-NativeJson $locatorPath
        if ($locator.owner -ne 'orquestrador-test-v1') { throw 'Instalacao nao reconhecida. Abra 01 - Instalar.vbs primeiro.' }
        $DataRoot = [string]$locator.root
    }
    $DataRoot = [IO.Path]::GetFullPath($DataRoot)
    Initialize-NativeLanguage $DataRoot
    $marker = Read-NativeJson (Join-Path $DataRoot 'instalacao-teste.json')
    if ($marker.owner -ne 'orquestrador-test-v1') { throw 'Esta pasta nao e uma instalacao CAIO reconhecida.' }
    if ($Action -eq 'open') {
        Open-NativeInstalled $DataRoot
    } else {
        & (Join-Path $PSScriptRoot 'Desinstalar.ps1') -DataRoot $DataRoot
        exit $LASTEXITCODE
    }
    exit 0
} catch {
    Show-NativeError $_.Exception.Message
    exit 2
}
