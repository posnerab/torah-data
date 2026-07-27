param(
    [string]$ServiceName = 'MSOLAP$SSAS2025',
    [ValidateSet('Automatic', 'Manual', 'Unchanged')]
    [string]$StartupType = 'Automatic'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CacheEngine.Common.ps1')
$service = Get-Service -Name $ServiceName -ErrorAction Stop
$startupMatches = $StartupType -eq 'Unchanged' -or
    $service.StartType.ToString() -eq $StartupType
if ($service.Status -eq 'Running' -and $startupMatches) {
    $service | Select-Object Name, Status, StartType
    exit 0
}
if (-not (Test-IsAdministrator)) {
    $argument = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath +
        '" -ServiceName "' + $ServiceName + '" -StartupType "' + $StartupType + '"'
    $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $argument `
        -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) {
        throw "Elevated service start failed with exit code $($process.ExitCode)."
    }
}
else {
    if ($StartupType -ne 'Unchanged') {
        Set-Service -Name $ServiceName -StartupType $StartupType
    }
    if ($service.Status -ne 'Running') {
        Start-Service -Name $ServiceName
    }
}
Get-Service -Name $ServiceName |
    Select-Object Name, Status, StartType
