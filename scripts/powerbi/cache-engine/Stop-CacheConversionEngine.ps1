param([string]$RuntimeRoot)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CacheEngine.Common.ps1')
$RuntimeRoot = Resolve-CacheEngineRuntimeRoot $RuntimeRoot

if (-not (Test-IsAdministrator)) {
    $argument = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath +
        '" -RuntimeRoot "' + $RuntimeRoot + '"'
    $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $argument `
        -WindowStyle Hidden -PassThru -Wait
    exit $process.ExitCode
}

$enginePidFile = Join-Path $RuntimeRoot 'conversion-engine.pid'
$hostPidFile = Join-Path $RuntimeRoot 'conversion-host.pid'
$enginePid = Get-Content -LiteralPath $enginePidFile -ErrorAction SilentlyContinue
if ($enginePid) {
    $engine = Get-Process -Id $enginePid -ErrorAction SilentlyContinue
    if ($engine) {
        Stop-Process -Id $enginePid -Force
        $engine.WaitForExit(10000)
    }
}
$hostPid = Get-Content -LiteralPath $hostPidFile -ErrorAction SilentlyContinue
if ($hostPid) {
    Wait-Process -Id $hostPid -Timeout 10 -ErrorAction SilentlyContinue
}
