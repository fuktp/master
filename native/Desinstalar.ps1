param([Parameter(Mandatory=$true)][string]$DataRoot)
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'Native.Common.ps1')
    $DataRoot = [IO.Path]::GetFullPath($DataRoot)
    Initialize-NativeLanguage $DataRoot
    $pointerPath = Join-Path $DataRoot 'installation.json'
    $planPath = Join-Path $DataRoot 'state\uninstall-cleanup.json'
    $owned = [IO.Path]::GetFullPath((Join-Path $DataRoot 'app\versions')) + [IO.Path]::DirectorySeparatorChar
    $completed = $false
    if (Test-Path -LiteralPath $pointerPath) {
        $pointer = Read-NativeJson $pointerPath
        $release = [IO.Path]::GetFullPath([string]$pointer.release)
        if ($pointer.distribution -ne 'native-scripts' -or -not $release.StartsWith($owned, [StringComparison]::OrdinalIgnoreCase)) { throw 'Versao fora da instalacao reconhecida.' }
        $manifest = Join-Path $release 'release.json'
        if ((Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pointer.manifest_sha256) { throw 'Manifesto alterado; repare a instalacao antes de desinstalar.' }
        $hostPath = Join-Path $release 'runtime\CAIO-Desinstalador.exe'
        if (-not (Test-Path -LiteralPath $hostPath)) { $hostPath = Join-Path $release 'runtime\pythonw.exe' }
        $process = Start-HiddenProcess $hostPath @('-B','-m','orquestrador_app','--data-root',$DataRoot,'--uninstall') (Join-Path $release 'src')
        $process.WaitForExit()
        if ($process.ExitCode -eq 3) { exit 3 }
        if ($process.ExitCode -ne 0) { throw 'A desinstalacao nao foi concluida. Consulte o diagnostico na pasta logs da instalacao.' }
        $completed = $true
    }
    if (Test-Path -LiteralPath $planPath) {
        $plan = Read-NativeJson $planPath
        if ($plan.owner -ne 'caio-uninstall-cleanup-v1' -or [IO.Path]::GetFullPath([string]$plan.root) -ne $DataRoot) { throw 'Plano de limpeza nao reconhecido.' }
        foreach ($entry in $plan.releases) {
            Remove-NativeOwnedRelease $entry $owned
        }
        $reportPath = Join-Path $DataRoot 'state\uninstalled.json'
        if (Test-Path -LiteralPath $reportPath) {
            $report = Read-NativeJson $reportPath
            $report.cleanup_pending = $false
            Write-NativeJson $reportPath $report
        }
        Remove-Item -LiteralPath $planPath
        $message = 'CAIO desinstalado. Configuracao, relatorios, historicos, scripts e backups foram preservados em: ' + $DataRoot
        if (@($plan.preserved_unverified).Count) { $message += "`nPastas nao verificadas foram preservadas: " + ($plan.preserved_unverified -join ', ') }
    } elseif ($completed) { $message = 'CAIO desinstalado. Os dados, backups e arquivos do aplicativo foram preservados conforme sua escolha em: ' + $DataRoot }
    else { $message = 'Os componentes do CAIO ja foram removidos. Os dados preservados continuam em: ' + $DataRoot }
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show((T $message), (T 'CAIO - Desinstalacao')) | Out-Null
    exit 0
} catch {
    Show-NativeError ($_.Exception.Message + "`nOs dados e backups foram preservados. Execute 03 - Desinstalar CAIO.vbs novamente para tentar concluir.")
    exit 2
}
