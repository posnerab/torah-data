param(
    [string]$ServiceName = 'MSOLAP$SSAS2025',
    [switch]$SetManual
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CacheEngine.Common.ps1')
if (-not (Test-IsAdministrator)) {
    $argument = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath +
        '" -ServiceName "' + $ServiceName + '"'
    if ($SetManual) {
        $argument += ' -SetManual'
    }
    $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $argument `
        -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) {
        throw "Elevated service stop failed with exit code $($process.ExitCode)."
    }
}
else {
    $service = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name $ServiceName -Force
    }
    if ($SetManual) {
        Set-Service -Name $ServiceName -StartupType Manual
    }
}
Get-Service -Name $ServiceName |
    Select-Object Name, Status, StartType
