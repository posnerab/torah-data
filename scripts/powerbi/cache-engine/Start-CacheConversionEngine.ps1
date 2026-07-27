param(
    [string]$RuntimeRoot,
    [string]$InstanceName = 'CacheConversionEngine',
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CacheEngine.Common.ps1')
$RuntimeRoot = Resolve-CacheEngineRuntimeRoot $RuntimeRoot
$hostScript = Join-Path $PSScriptRoot 'Host-CacheConversionEngine.ps1'
$data = Join-Path $RuntimeRoot 'workspace\Data'
$enginePidFile = Join-Path $RuntimeRoot 'conversion-engine.pid'
$hostPidFile = Join-Path $RuntimeRoot 'conversion-host.pid'
$portFile = Join-Path $data 'msmdsrv.port.txt'

$existingPid = Get-Content -LiteralPath $enginePidFile -ErrorAction SilentlyContinue
if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
    $port = (Get-Content -LiteralPath $portFile -Raw).
        Replace([string][char]0, '').Trim()
    [pscustomobject]@{ ProcessId = [int]$existingPid; Port = [int]$port }
    exit 0
}

Remove-Item -LiteralPath $enginePidFile, $hostPidFile, $portFile -Force `
    -ErrorAction SilentlyContinue
$argument = '-NoProfile -ExecutionPolicy Bypass -File "' + $hostScript +
    '" -RuntimeRoot "' + $RuntimeRoot + '" -InstanceName "' + $InstanceName + '"'
Start-Process powershell.exe -Verb RunAs -ArgumentList $argument `
    -WindowStyle Hidden | Out-Null

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Milliseconds 250
    $enginePid = Get-Content -LiteralPath $enginePidFile -ErrorAction SilentlyContinue
    $hostPid = Get-Content -LiteralPath $hostPidFile -ErrorAction SilentlyContinue
    $engine = if ($enginePid) {
        Get-Process -Id $enginePid -ErrorAction SilentlyContinue
    }
    $hostProcess = if ($hostPid) {
        Get-Process -Id $hostPid -ErrorAction SilentlyContinue
    }
    if ($enginePid -and -not $engine) {
        throw "Conversion engine process $enginePid exited during startup."
    }
    if ($hostPid -and -not $hostProcess) {
        throw "Conversion host process $hostPid exited during startup."
    }
} until (($engine -and (Test-Path -LiteralPath $portFile)) -or
    (Get-Date) -gt $deadline)

if (-not $engine) {
    throw "Conversion engine did not start within $TimeoutSeconds seconds."
}
$port = (Get-Content -LiteralPath $portFile -Raw).
    Replace([string][char]0, '').Trim()
[pscustomobject]@{ ProcessId = [int]$enginePid; Port = [int]$port }
