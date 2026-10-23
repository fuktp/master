param([switch]$Run, [string]$Output = "$env:TEMP\CAIO-Windows-validation.json")
$ErrorActionPreference = 'Stop'
if (-not $Run) { throw 'Para iniciar os testes temporarios no Windows, execute este script com -Run. Leia docs/VALIDACAO.md nas fontes.' }
$package = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtime = Join-Path $package 'payload\runtime\pythonw.exe'
$script = Join-Path $package 'payload\src\release_tools\validate_windows_release.py'
$payload = Join-Path $package 'payload'
$arguments = '"{0}" --payload "{1}" --output "{2}"' -f $script, $payload, $Output
$process = Start-Process -FilePath $runtime -ArgumentList $arguments -WorkingDirectory $package -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Validacao incompleta; consulte $Output. Codigo: $($process.ExitCode)" }
Write-Output "Evidencias salvas em $Output. Confira os itens manuais e a imagem da VM antes de homologar."
