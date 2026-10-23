param([string]$DataRoot = '', [switch]$Agent)
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'Native.Common.ps1')
    if (-not $DataRoot) { $DataRoot = Split-Path -Parent $PSScriptRoot }
    $DataRoot = [IO.Path]::GetFullPath($DataRoot)
    Initialize-NativeLanguage $DataRoot
    $marker = Read-NativeJson (Join-Path $DataRoot 'instalacao-teste.json')
    if ($marker.owner -ne 'orquestrador-test-v1') { throw 'Esta pasta não é uma instalação de teste reconhecida.' }
    $journalPath = Join-Path $DataRoot 'state\native-transaction.json'
    if (Test-Path -LiteralPath $journalPath) {
        $journal = Read-NativeJson $journalPath
        if ($journal.status -notin @('committed', 'rolled_back')) {
            $recovery = [string]$journal.new
            if (-not (Test-Path -LiteralPath (Join-Path $recovery 'runtime\pythonw.exe'))) { $recovery = [string]$journal.recovery_release }
            $job = Start-NativeBridge $recovery @{ action = 'recover'; data_root = $DataRoot }
            if (-not $job.Process.WaitForExit(180000)) { throw 'A recuperação continua em segundo plano; aguarde antes de abrir novamente.' }
            Get-NativeBridgeResult $job | Out-Null
        }
    }
    $pointer = Read-NativeJson (Join-Path $DataRoot 'installation.json')
    if ($pointer.distribution -ne 'native-scripts') { throw 'Distribuição de scripts não reconhecida.' }
    $release = [IO.Path]::GetFullPath([string]$pointer.release)
    $managed = [IO.Path]::GetFullPath((Join-Path $DataRoot 'app\versions')) + [IO.Path]::DirectorySeparatorChar
    if (-not $release.StartsWith($managed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Versão fora da pasta gerenciada.' }
    $manifest = Join-Path $release 'release.json'
    if ((Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pointer.manifest_sha256) { throw 'Manifesto da versão foi alterado; abra o wizard para reparar.' }
    $arguments = @('-B', '-m', 'orquestrador_app', '--data-root', $DataRoot)
    if ($Agent) { $arguments += '--agent' }
    $hostName = if ($Agent) { 'CAIO-Monitor.exe' } else { 'CAIO-Orquestrador.exe' }
    $executable = Join-Path $release ('runtime\' + $hostName)
    if (-not (Test-Path -LiteralPath $executable)) { $executable = Join-Path $release 'runtime\pythonw.exe' }
    Start-HiddenProcess $executable $arguments (Join-Path $release 'src') | Out-Null
    exit 0
} catch {
    if (-not $Agent) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show((T $_.Exception.Message), (T 'Orquestrador • falha ao abrir')) | Out-Null
    }
    exit 2
}
