param(
    [string]$RuntimeRoot,
    [string]$ServerName = 'localhost\SSAS2025',
    [string]$ServiceName = 'MSOLAP$SSAS2025'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CacheEngine.Common.ps1')
$RuntimeRoot = Resolve-CacheEngineRuntimeRoot $RuntimeRoot
$service = Get-Service -Name $ServiceName -ErrorAction Stop
$databases = @()
if ($service.Status -eq 'Running') {
    Import-CacheEngineAmo $RuntimeRoot
    $server = [Microsoft.AnalysisServices.Tabular.Server]::new()
    try {
        $server.Connect($ServerName)
        $databases = @(
            $server.Databases |
                Select-Object Name, CompatibilityLevel,
                    @{ Name = 'TableCount'; Expression = { $_.Model.Tables.Count } }
        )
    }
    finally {
        if ($server.Connected) {
            $server.Disconnect()
        }
    }
}
[pscustomobject]@{
    Server = $ServerName
    ServiceName = $service.Name
    ServiceStatus = $service.Status
    StartType = $service.StartType
    Databases = $databases
    ConversionEngineRunning = [bool](
        Get-Content -LiteralPath (Join-Path $RuntimeRoot 'conversion-engine.pid') `
            -ErrorAction SilentlyContinue |
            ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
    )
    PowerBIDesktopCount = @(Get-Process PBIDesktop -ErrorAction SilentlyContinue).Count
}
