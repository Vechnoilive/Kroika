$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$version = (Get-Content "$root\backend\src\kroika_backend\desktop_version.py" | Select-String '^VERSION = "(.*)"').Matches.Groups[1].Value
$installer = "$root\dist\desktop\Kroika-$version-windows-x64-setup.exe"
$testRoot = Join-Path $env:RUNNER_TEMP 'Kroika installed тест # path'
if (-not $env:RUNNER_TEMP) { $testRoot = Join-Path ([IO.Path]::GetTempPath()) ('Kroika-test-' + [guid]::NewGuid()) }
$app = Join-Path $testRoot 'application'
$profile = Join-Path $testRoot 'profile'
New-Item -ItemType Directory -Force -Path $testRoot,$profile | Out-Null

function Run-Checked([string]$program, [string[]]$arguments) {
    $process = Start-Process -FilePath $program -ArgumentList $arguments -PassThru
    if (-not $process.WaitForExit(180000)) { $process.Kill(); throw "Process timed out: $program" }
    if ($process.ExitCode -ne 0) {
        foreach ($name in @('bundle.json','window.json','updated-window.json')) {
            $report = Join-Path $testRoot $name
            if (Test-Path $report) { Get-Content -LiteralPath $report -Raw | Write-Output }
        }
        throw "Process failed: $program (exit $($process.ExitCode))"
    }
}

function Assert-Report([string]$path) {
    $report = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if (-not $report.ok) { throw "Installed diagnostic failed: $($report.error_type)" }
    $report | ConvertTo-Json -Compress | Write-Output
}

$originalPath = $env:PATH
$originalHome = $env:KROIKA_DESKTOP_HOME
$originalPythonPath = $env:PYTHONPATH
$originalWorking = Get-Location
try {
    Run-Checked $installer @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$app`"", "/LOG=`"$testRoot\install.log`"")
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONPATH = ''
    $env:KROIKA_DESKTOP_HOME = $profile
    Set-Location $testRoot
    if (Get-Command python,node,npm,py -ErrorAction SilentlyContinue) { throw 'Developer runtimes still visible in PATH' }
    $exe = Join-Path $app 'Kroika.exe'
    Run-Checked $exe @('--self-test', "`"$testRoot\bundle.json`"")
    Assert-Report "$testRoot\bundle.json"
    Run-Checked $exe @('--smoke-test', "`"$testRoot\window.json`"")
    Assert-Report "$testRoot\window.json"
    $database = Join-Path $profile 'data\kroika.db'
    $before = (Get-FileHash -LiteralPath $database).Hash
    $settings = Join-Path $profile 'settings.json'
    $document = @{version=1;provider='mock';model='gemini-3.6-flash';thinking='auto';timeout=300;max_output_tokens=16384;api_mode='generate_content';attempts=3;key_mode='none'}
    [IO.File]::WriteAllText($settings, ($document | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    $settingsBefore = (Get-FileHash -LiteralPath $settings).Hash
    $sentinel = Join-Path $profile 'data\images\retained-file.txt'
    [IO.File]::WriteAllText($sentinel, 'preserve user files')
    [IO.File]::WriteAllText((Join-Path $app '_internal\obsolete-test-file.txt'), 'old runtime')
    [IO.File]::WriteAllText((Join-Path $profile 'installed-version.json'), '{"version":"0.2.0"}', [Text.UTF8Encoding]::new($false))
    Run-Checked $installer @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$app`"", "/LOG=`"$testRoot\upgrade.log`"")
    if (Test-Path (Join-Path $app '_internal\obsolete-test-file.txt')) { throw 'Obsolete packaged runtime not removed' }
    if ((Get-FileHash -LiteralPath $database).Hash -ne $before) { throw 'Installer changed user database' }
    if ((Get-FileHash -LiteralPath $settings).Hash -ne $settingsBefore) { throw 'Installer changed AI settings' }
    if (-not (Test-Path $sentinel)) { throw 'Installer removed user image folder' }
    Run-Checked $exe @('--smoke-test', "`"$testRoot\updated-window.json`"")
    Assert-Report "$testRoot\updated-window.json"
    if (-not (Get-ChildItem -Path (Join-Path $profile 'backups') -Filter 'before-desktop-*' -Directory)) { throw 'Pre-upgrade data snapshot missing' }
    Run-Checked (Join-Path $app 'unins000.exe') @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$testRoot\uninstall.log`"")
    if (-not (Test-Path $database) -or -not (Test-Path $sentinel)) { throw 'Uninstall removed user data' }
    if ((Get-FileHash -LiteralPath $settings).Hash -ne $settingsBefore) { throw 'Uninstall changed AI settings' }
    Write-Output 'Installed application, WebView2 window, upgrade and uninstall passed without Python/Node in PATH.'
} finally {
    Set-Location $originalWorking
    $env:PATH = $originalPath
    $env:PYTHONPATH = $originalPythonPath
    $env:KROIKA_DESKTOP_HOME = $originalHome
}
