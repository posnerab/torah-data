Set-StrictMode -Version Latest

function Resolve-CacheEngineRuntimeRoot {
    param([string]$RuntimeRoot)

    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $RuntimeRoot = $env:AS_CACHE_ENGINE_RUNTIME_ROOT
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        throw 'Specify -RuntimeRoot or set AS_CACHE_ENGINE_RUNTIME_ROOT.'
    }

    $resolved = [IO.Path]::GetFullPath($RuntimeRoot)
    foreach ($required in 'bin\msmdsrv.exe', 'workspace\Data\msmdsrv.ini',
        'clients\amo\Microsoft.AnalysisServices.Core.dll',
        'clients\amo\Microsoft.AnalysisServices.Tabular.dll',
        'clients\adomd\Microsoft.AnalysisServices.AdomdClient.dll') {
        $path = Join-Path $resolved $required
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Runtime component not found: $path"
        }
    }
    $resolved
}

function Import-CacheEngineAmo {
    param([Parameter(Mandatory)][string]$RuntimeRoot)

    if (-not ('Microsoft.AnalysisServices.Tabular.Server' -as [type])) {
        $amo = Join-Path $RuntimeRoot 'clients\amo'
        Add-Type -Path (Join-Path $amo 'Microsoft.AnalysisServices.Core.dll')
        Add-Type -Path (Join-Path $amo 'Microsoft.AnalysisServices.Tabular.dll')
    }
}

function Invoke-CacheEngineXmla {
    param(
        [Parameter(Mandatory)][string]$ServerName,
        [Parameter(Mandatory)][string]$Xmla
    )

    $server = [Microsoft.AnalysisServices.Tabular.Server]::new()
    try {
        $server.Connect($ServerName)
        $result = $server.Execute($Xmla)
        $errors = @(
            $result |
                ForEach-Object { $_.Messages } |
                Where-Object { $_.ErrorCode -ne 0 }
        )
        if ($errors) {
            throw ($errors | ForEach-Object { $_.Description } | Out-String)
        }
    }
    finally {
        if ($server.Connected) {
            $server.Disconnect()
        }
    }
}

function ConvertTo-SafeCacheFileName {
    param([Parameter(Mandatory)][string]$DatabaseName)

    $invalid = [IO.Path]::GetInvalidFileNameChars()
    $characters = foreach ($character in $DatabaseName.ToCharArray()) {
        if ($invalid -contains $character) { '_' } else { $character }
    }
    $safe = (-join $characters).Trim().TrimEnd('.')
    if ([string]::IsNullOrWhiteSpace($safe)) {
        throw 'DatabaseName does not contain a usable filename.'
    }
    $safe
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
