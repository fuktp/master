param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$files = @(Get-ChildItem -LiteralPath (Join-Path $Root 'native') -Filter '*.ps1')
$count = 0
foreach ($file in $files) {
    $tokens = $null; $parseErrors = $null
    [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0) { throw ($file.Name + ': ' + ($parseErrors.Message -join '; ')) }
    $count++
}
. (Join-Path $Root 'native/Native.Common.ps1')
. (Join-Path $Root 'native/Native.Routines.ps1')
$translationCatalog = Read-NativeJson (Join-Path $Root 'orquestrador_app/locales.json')
foreach ($property in $translationCatalog.PSObject.Properties) {
    if ($property.Value.Count -ne 2 -or -not $property.Value[0] -or -not $property.Value[1]) {
        throw "Traduções incompletas: $($property.Name)"
    }
}
foreach ($key in @('Desabilitada', 'desabilitada')) {
    $entry = $translationCatalog.PSObject.Properties[$key]
    if ($null -eq $entry -or $entry.Value[0] -cne 'Disabled' -or $entry.Value[1] -cne 'Deshabilitada') {
        throw "Catálogo incompatível com a consulta do wizard: $key"
    }
}
$count++
$script:visualTheme = Read-NativeJson (Join-Path $Root 'assets/dashboard-theme.json')
if ((Get-NativeThemeColor 'firstLevelElements').ToArgb() -ne [Drawing.ColorTranslator]::FromHtml('#00338D').ToArgb()) {
    throw 'A identidade KPMG do tema não foi aplicada pelo adaptador nativo.'
}
$count++
$originalAccent = $script:visualTheme.accent
try {
    $script:visualTheme.accent = '#255580'
    if ((Get-NativeThemeColor 'accent').ToArgb() -ne [Drawing.ColorTranslator]::FromHtml('#255580').ToArgb()) {
        throw 'O adaptador nativo usou uma cor fixa em vez do tema.'
    }
} finally { $script:visualTheme.accent = $originalAccent }
$count++
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('orquestrador-powershell-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
try {
    $file = Join-Path $temporary 'config.json'
    Write-NativeJson $file @{ value = 'João com espaços'; version = 1 }
    Write-NativeJson $file @{ value = 'configuração preservada'; version = 2 }
    $value = Read-NativeJson $file
    if ($value.version -ne 2 -or $value.value -ne 'configuração preservada') { throw 'Escrita JSON atômica falhou.' }
    $count++
    foreach ($email in @('', '   ', 'sem-arroba', 'pessoa@', 'pessoa @exemplo.com', 'Nome <pessoa@exemplo.com>')) {
        if (Test-NativeEmail $email) { throw "E-mail inválido aceito: $email" }
    }
    foreach ($email in @('pessoa@exemplo.com', ' pessoa+teste@sub.exemplo.com.br ')) {
        if (-not (Test-NativeEmail $email)) { throw "E-mail válido recusado: $email" }
    }
    $count++
    foreach ($case in @(@('daily',0,'0,1,2,3,4,5,6'), @('weekly',3,'3'), @('every_run',0,'0,1,2,3,4,5,6'), @('weekdays',0,'0,1,2,3,4'))) {
        $days = @(Get-NativeDayPreset $case[0] $case[1])
        if (($days -join ',') -ne $case[2] -or -not (Test-NativeDayPreset $case[0] $days $case[1])) { throw "Padrão de dias incorreto: $($case[0])" }
        $count++
    }
    if (Test-NativeDayPreset 'daily' @(0,1,2,3,4)) { throw 'Calendário personalizado foi tratado como diária padrão.' }
    if (Test-NativeDayPreset 'weekly' @(0,1,2,3,4)) { throw 'Calendário personalizado foi tratado como semanal padrão.' }
    if (-not (Test-NativeDayPreset 'weekly' @(4))) { throw 'Sexta-feira isolada deve ser semanal padrão.' }
    $count++

    # Execute the real page handlers and shared actions with dialog doubles, not WinForms.
    Add-Type -TypeDefinition @'
namespace Windows.Forms {
    public class OpenFileDialog {
        public static string SelectedPath;
        public string Filter { get; set; }
        public string FileName { get { return SelectedPath; } }
        public string ShowDialog(object owner) { return "OK"; }
        public void Dispose() { }
    }
    public static class MessageBox {
        public static string Answer = "No";
        public static string Show(object owner, string message, string title, string buttons, string icon, string defaultButton) { return Answer; }
    }
}
'@
    $wizard = [Management.Automation.Language.Parser]::ParseFile((Join-Path $Root 'native/wizard.ps1'), [ref]$null, [ref]$null)
    $handlers = @{}
    foreach ($node in $wizard.FindAll({ param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $n.Member.Value -eq 'Add_Click' }, $true)) {
        $name = $node.Expression.Extent.Text
        if ($name -in @('$destinationAdd','$destinationRemove','$addJob','$removeJob','$next')) { $handlers[$name] = $node.Arguments[0].ScriptBlock.GetScriptBlock() }
    }
    function Show-NativeRemovalConfirmation($Owner, [string]$Message) { return [Windows.Forms.MessageBox]::Answer -eq 'Yes' }
    function Collect-Configuration { $script:collected++ }
    function Refresh-RoutineRows { $script:refreshed++ }
    function Start-Operation([string]$Action) { $script:actions += $Action }
    function Show-NativeError([string]$Message) { $script:shownError = $Message }
    function Show-Page([int]$Index) { $script:shownPage = $Index }
    $form = $null; $script:job = $null
    $script:actions = @(); $script:collected = 0; $script:refreshed = 0; $script:shownError = ''
    $script:shownPage = -1; $script:pageIndex = 2
    $email = [pscustomobject]@{Text=''; Focused=$false}
    $email | Add-Member ScriptMethod Focus { $this.Focused=$true; return $true }
    & $handlers['$next']
    if ($script:shownPage -ne -1 -or -not $email.Focused -or -not $script:shownError) { throw 'A página 3 avançou sem e-mail.' }
    $count++
    $email.Text = 'pessoa@exemplo.com'
    & $handlers['$next']
    if ($script:shownPage -ne 3) { throw 'A página 3 não avançou com e-mail válido.' }
    $count++
    $destinations = [pscustomobject]@{ CurrentRow = [pscustomobject]@{ Index = 1 } }
    $routines = [pscustomobject]@{ CurrentRow = [pscustomobject]@{ Index = 0 } }
    [Windows.Forms.OpenFileDialog]::SelectedPath = Join-Path $temporary 'script com espaços.py'
    foreach ($case in @(@('$destinationAdd',3), @('$addJob',4))) {
        $script:pageIndex = $case[1]
        $before = $script:actions.Count
        & $handlers[$case[0]]
        if ($script:actions.Count -ne $before+1 -or $script:actions[-1] -ne 'add_script' -or $script:addScriptPage -ne $case[1] -or $script:addScript -ne [Windows.Forms.OpenFileDialog]::SelectedPath) { throw "Adicionar não acionou a ponte na página $($case[1]+1)." }
        $count++
    }
    $script:config = [pscustomobject]@{ routines = @(
        [pscustomobject]@{ id='a'; order=0; dependencies=@() },
        [pscustomobject]@{ id='b'; order=1; dependencies=@() }) }
    & $handlers['$destinationRemove']
    if ($script:config.routines.Count -ne 2) { throw 'Cancelar a remoção alterou o cadastro.' }
    $count++
    [Windows.Forms.MessageBox]::Answer = 'Yes'
    & $handlers['$destinationRemove']
    if ($script:config.routines.Count -ne 1 -or $script:config.routines[0].id -ne 'a') { throw 'Retirar na página 4 não removeu a seleção correta.' }
    $count++
    & $handlers['$removeJob']
    if ($script:config.routines.Count -ne 0 -or $script:refreshed -ne 2) { throw 'Retirar na página 5 não atualizou as duas tabelas.' }
    $count++
    $script:config.routines = @(
        [pscustomobject]@{ id='a'; order=0; dependencies=@() },
        [pscustomobject]@{ id='b'; order=1; dependencies=@([pscustomobject]@{job='a'}) })
    & $handlers['$removeJob']
    if ($script:config.routines.Count -ne 2 -or -not $script:shownError) { throw 'Foi aceita remoção com dependente ativo.' }
    $count++
    if ((Quote-NativeArgument 'C:\uma pasta\') -ne '"C:\uma pasta\\"') { throw 'Escape de caminho com espaços/barra final falhou.' }
    $count++
    $reuseRejected = $false
    try { Wait-OwnedParent ([Diagnostics.Process]::GetCurrentProcess().Id) 0 1 } catch { $reuseRejected = $true }
    if (-not $reuseRejected) { throw 'Reutilização de PID não foi rejeitada.' }
    $count++
    Wait-OwnedParent 2147483000 0 1
    $count++
    $cleanupOwned = Join-Path $temporary 'owned-versions'
    New-Item -ItemType Directory -Path $cleanupOwned | Out-Null
    $cleanupOwned += [IO.Path]::DirectorySeparatorChar
    function New-CleanupFixture([string]$Name) {
        $directory = Join-Path $cleanupOwned $Name
        New-Item -ItemType Directory -Path $directory | Out-Null
        [IO.File]::WriteAllText((Join-Path $directory 'own.txt'), 'ação preservada')
        $hash = (Get-FileHash -LiteralPath (Join-Path $directory 'own.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-NativeJson (Join-Path $directory 'release.json') @{owner='orquestrador-native-package-v1'; files=@{'own.txt'=$hash}}
        return [pscustomobject]@{path=$directory; manifest_sha256=(Get-FileHash -LiteralPath (Join-Path $directory 'release.json') -Algorithm SHA256).Hash.ToLowerInvariant(); files=[pscustomobject]@{'own.txt'=$hash}}
    }
    $entry = New-CleanupFixture 'full'
    Remove-NativeOwnedRelease $entry $cleanupOwned
    if (Test-Path -LiteralPath $entry.path) { throw 'Limpeza completa nao removeu a versao.' }
    $count++
    $entry = New-CleanupFixture 'external'
    [IO.File]::WriteAllText((Join-Path $entry.path 'external.txt'), 'preservar')
    $refused = $false
    try { Remove-NativeOwnedRelease $entry $cleanupOwned } catch { $refused = $true }
    if (-not $refused -or -not (Test-Path -LiteralPath (Join-Path $entry.path 'own.txt'))) { throw 'Limpeza nao preservou versao com arquivo externo.' }
    $count++
    $entry = New-CleanupFixture 'changed'
    [IO.File]::WriteAllText((Join-Path $entry.path 'own.txt'), 'alterado')
    $refused = $false
    try { Remove-NativeOwnedRelease $entry $cleanupOwned } catch { $refused = $true }
    if (-not $refused -or -not (Test-Path -LiteralPath (Join-Path $entry.path 'own.txt'))) { throw 'Limpeza aceitou arquivo alterado.' }
    $count++
    $entry = New-CleanupFixture 'retry'
    Remove-Item -LiteralPath (Join-Path $entry.path 'own.txt')
    Remove-NativeOwnedRelease $entry $cleanupOwned
    if (Test-Path -LiteralPath $entry.path) { throw 'Limpeza parcial nao pode ser retomada.' }
    $count++
    $savedLocalAppData = $env:LOCALAPPDATA
    try {
        $env:LOCALAPPDATA = Join-Path $temporary 'local-data'
        $invalid = Join-Path $temporary 'not-executable.exe'
        [IO.File]::WriteAllText($invalid, 'not a valid Windows executable')
        $failure = ''
        try { Start-HiddenProcess $invalid @('secret-not-for-diagnostic') $temporary | Out-Null } catch { $failure = $_.Exception.Message }
        if (-not $failure.Contains($invalid) -or -not $failure.Contains('Codigo nativo:') -or -not $failure.Contains($temporary)) { throw 'Falha de execucao perdeu executavel, pasta ou codigo nativo.' }
        $reports = @(Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Orquestrador-Teste/bootstrap') -Filter 'start-error-*.json')
        if ($reports.Count -ne 1) { throw 'Falha de execucao nao gerou diagnostico.' }
        $diagnostic = Read-NativeJson $reports[0].FullName
        if (-not $diagnostic.native_code -or $diagnostic.executable -ne $invalid -or (Get-Content -LiteralPath $reports[0].FullName -Raw).Contains('secret-not-for-diagnostic')) { throw 'Diagnostico incorreto ou inclui argumentos.' }
        $count++
        # A named application host exists, but setup must still select the untouched interpreter.
        $bridgePayload = Join-Path $temporary 'bridge-payload'
        New-Item -ItemType Directory -Path (Join-Path $bridgePayload 'runtime'),(Join-Path $bridgePayload 'src') | Out-Null
        [IO.File]::WriteAllText((Join-Path $bridgePayload 'runtime/pythonw.exe'), 'original fixture')
        [IO.File]::WriteAllText((Join-Path $bridgePayload 'runtime/CAIO-Orquestrador.exe'), 'named fixture')
        function Start-HiddenProcess([string]$File, [string[]]$Arguments, [string]$WorkingDirectory) {
            $script:bridgeExecutable = $File
            return [pscustomobject]@{HasExited=$true; ExitCode=0}
        }
        $bridge = Start-NativeBridge $bridgePayload @{action='preview'; data_root=$temporary}
        if ($script:bridgeExecutable -ne (Join-Path $bridgePayload 'runtime/pythonw.exe') -or -not (Test-Path -LiteralPath (Join-Path $bridge.Work 'request.json'))) { throw 'Preview da pagina 2 deixou de usar o interpretador original.' }
        $count++
    } finally {
        $env:LOCALAPPDATA = $savedLocalAppData
        . (Join-Path $Root 'native/Native.Common.ps1')
    }
    $languageHandler = $wizard.FindAll({param($node) $node -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $node.Expression.Extent.Text -eq '$languageChoice' -and $node.Member.Value -eq 'Add_SelectedIndexChanged'}, $true)[0].Arguments[0].ScriptBlock.GetScriptBlock()
    $languageChoice = [pscustomobject]@{SelectedIndex=2}
    $script:config = [pscustomobject]@{language='es'}
    $script:pages = @(); $script:pageIndex=0
    $script:collected=0; $script:refreshed=0; $script:fillingConfiguration=$true
    & $languageHandler
    if ($script:collected -ne 0 -or $script:refreshed -ne 0) { throw 'Mudar idioma durante leitura substituiu dados da configuracao.' }
    $script:fillingConfiguration=$false
    & $languageHandler
    if ($script:collected -ne 1 -or $script:refreshed -ne 1) { throw 'Mudar idioma nao preservou valores editados.' }
    $count++
    $script:catalog = $translationCatalog
    try {
        foreach ($locale in @('en','es')) {
            Set-NativeLanguage $locale
            $position = if ($locale -eq 'en') { 0 } else { 1 }
            foreach ($entry in $translationCatalog.PSObject.Properties) {
                if ((T $entry.Name) -cne [string]$entry.Value[$position]) { throw ('Traducao nativa ausente: ' + $entry.Name) }
                $tokens = @([regex]::Matches($entry.Name, '\{\d+\}') | ForEach-Object {$_.Value} | Sort-Object)
                $translatedTokens = @([regex]::Matches([string]$entry.Value[$position], '\{\d+\}') | ForEach-Object {$_.Value} | Sort-Object)
                if (($tokens -join ',') -ne ($translatedTokens -join ',')) { throw ('Campos dinamicos divergentes: ' + $entry.Name) }
            }
        }
        $count++
        Set-NativeLanguage 'en'
        if ((T 'Arquivos copiados: 21 / 99') -cne 'Files copied: 21 / 99') { throw 'Progresso dinamico nao traduzido.' }
        $count++
        Set-NativeLanguage 'es'
        $userPath = 'C:\Ação\Diária {1}.exe'
        $message = T ("Falha ao iniciar processo. Codigo nativo: 5`nExecutavel: " + $userPath)
        if (-not $message.Contains('Código nativo: 5') -or -not $message.Contains('Ejecutable: ' + $userPath)) { throw 'Diagnostico multilinha perdeu traducao ou alterou dados.' }
        if ((T 'Rotina • Diária') -cne 'Rutina • Diária') { throw 'Nome de rotina foi retraduzido.' }
        $count++
        if ((T 'TESTE ISOLADO • Versão {0} • Runtime privado • Versionamento interno' @('2.0.0.dev13')) -notmatch 'PRUEBA AISLADA.*2.0.0.dev13') { throw 'Valores explicitos nao aplicados ao cabecalho.' }
        if ([Threading.Thread]::CurrentThread.CurrentUICulture.Name -ne 'es-ES') { throw 'Cultura do wizard nao acompanha idioma.' }
        $count++
    } finally { Set-NativeLanguage 'pt-BR' }
    foreach ($script in $files) {
        $content = Get-Content -LiteralPath $script.FullName -Raw
        if ($content -match '(?im)^\s*(Set-ExecutionPolicy|Unblock-File|Add-MpPreference|Set-MpPreference)\b') { throw 'Alteração de política de segurança não autorizada.' }
    }
    $count++
    @{ checks = $count; result = 'passed'; environment = [Environment]::OSVersion.ToString(); powershell = $PSVersionTable.PSVersion.ToString(); wizard_actions = 'real handlers with dialog doubles'; winforms_executed = $false; scheduled_tasks_executed = $false } | ConvertTo-Json
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
