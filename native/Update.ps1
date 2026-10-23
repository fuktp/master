param(
    [string]$PackageRoot = '',
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [int]$OwnerPid = 0,
    [double]$OwnerStarted = 0,
    [string]$Backup = ''
)
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'Native.Common.ps1')
    Wait-OwnedParent $OwnerPid $OwnerStarted
    $wizard = Join-Path $PSScriptRoot 'wizard.ps1'
    & $wizard -PackageRoot $PackageRoot -DataRoot $DataRoot -Backup $Backup -AutoUpdate
    exit $LASTEXITCODE
} catch {
    Show-NativeError ($_.Exception.Message + "`r`nA versão anterior permanece disponível pelo atalho do produto.")
    exit 2
}
