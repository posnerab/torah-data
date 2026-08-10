[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Doctor', 'Validate', 'Open', 'Status', 'Manifest', 'Save', 'Reload', 'Screenshot', 'ScreenshotAll')]
    [string]$Action,

    [int]$ProcessId,
    [string]$PageId,
    [string]$OutputPath,
    [ValidateRange(1, 3)]
    [int]$Scale = 2,
    [ValidateRange(1, 600)]
    [int]$WaitSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$projectPath = Join-Path $repoRoot 'T-Projects.pbip'
$reportPath = Join-Path $repoRoot 'T-Projects.Report'
$workspaceRoot = Split-Path $repoRoot -Parent
$defaultArtifactDir = Join-Path $workspaceRoot 'tmp\powerbi-bridge'

function Resolve-PowerBIDesktopExe {
    if ($env:PBI_DESKTOP_PATH -and (Test-Path -LiteralPath $env:PBI_DESKTOP_PATH)) {
        return (Resolve-Path -LiteralPath $env:PBI_DESKTOP_PATH).Path
    }

    $conventionalPaths = @(
        (Join-Path $env:ProgramFiles 'Microsoft Power BI Desktop\bin\PBIDesktop.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Power BI Desktop\bin\PBIDesktop.exe')
    )
    foreach ($path in $conventionalPaths) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            return $path
        }
    }

    $storePackage = Get-AppxPackage -Name 'Microsoft.MicrosoftPowerBIDesktop' -ErrorAction SilentlyContinue |
        Sort-Object Version -Descending |
        Select-Object -First 1
    if ($storePackage) {
        $storeExe = Join-Path $storePackage.InstallLocation 'bin\PBIDesktop.exe'
        if (Test-Path -LiteralPath $storeExe) {
            return $storeExe
        }
    }

    throw 'PBIDesktop.exe was not found. Set PBI_DESKTOP_PATH to its full path.'
}

function Get-BridgeStatus {
    param([int]$BridgeProcessId)

    $arguments = @('status', '--wait-seconds', [string]$WaitSeconds)
    if ($BridgeProcessId -gt 0) {
        $arguments += @('--pid', [string]$BridgeProcessId)
    }

    $raw = & powerbi-desktop @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "powerbi-desktop status failed: $raw"
    }

    return ($raw | ConvertFrom-Json)
}

switch ($Action) {
    'Doctor' {
        & powerbi-report-author doctor --pretty
        exit $LASTEXITCODE
    }
    'Validate' {
        & powerbi-report-author validate $reportPath --pretty
        exit $LASTEXITCODE
    }
    'Open' {
        $env:PBI_DESKTOP_PATH = Resolve-PowerBIDesktopExe
        & powerbi-desktop open $projectPath --timeout ([string]$WaitSeconds)
        exit $LASTEXITCODE
    }
    'Status' {
        $status = Get-BridgeStatus -BridgeProcessId $ProcessId
        $status | ConvertTo-Json -Depth 12
    }
    'Manifest' {
        if ($ProcessId -le 0) {
            throw '-ProcessId is required for Manifest.'
        }
        & powerbi-desktop manifest --pid $ProcessId
        exit $LASTEXITCODE
    }
    'Save' {
        if ($ProcessId -le 0) {
            throw '-ProcessId is required for Save.'
        }

        & (Join-Path $PSScriptRoot 'ui_automation\Save-PowerBIDesktop.ps1') `
            -Action Save `
            -ProcessId $ProcessId `
            -ExpectedProjectPath $projectPath `
            -WaitSeconds ([Math]::Min($WaitSeconds, 60))
        exit $LASTEXITCODE
    }
    'Reload' {
        if ($ProcessId -le 0) {
            throw '-ProcessId is required for Reload.'
        }

        $status = Get-BridgeStatus -BridgeProcessId $ProcessId
        $instance = @($status.instances) | Where-Object pid -eq $ProcessId | Select-Object -First 1
        if (-not $instance) {
            throw "Power BI Desktop process $ProcessId was not returned by the bridge."
        }
        if ($instance.hasUnsavedChanges) {
            throw 'Power BI Desktop has unsaved UI changes. Save or discard them in Desktop before reloading PBIR files.'
        }

        & powerbi-desktop reload --pid $ProcessId --wait-seconds ([string]$WaitSeconds)
        exit $LASTEXITCODE
    }
    'Screenshot' {
        if ($ProcessId -le 0) {
            throw '-ProcessId is required for Screenshot.'
        }
        if (-not $PageId) {
            throw '-PageId is required for Screenshot.'
        }

        if (-not $OutputPath) {
            New-Item -ItemType Directory -Force -Path $defaultArtifactDir | Out-Null
            $OutputPath = Join-Path $defaultArtifactDir "$PageId.png"
        }

        & powerbi-desktop screenshot $PageId `
            --pid $ProcessId `
            --output $OutputPath `
            --scale ([string]$Scale) `
            --wait-seconds ([string]$WaitSeconds)
        exit $LASTEXITCODE
    }
    'ScreenshotAll' {
        if ($ProcessId -le 0) {
            throw '-ProcessId is required for ScreenshotAll.'
        }

        if (-not $OutputPath) {
            $OutputPath = Join-Path $defaultArtifactDir 'all-pages'
        }
        New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null

        & powerbi-desktop screenshot-all `
            --pid $ProcessId `
            --output-dir $OutputPath `
            --scale ([string]$Scale) `
            --wait-seconds ([string]$WaitSeconds)
        exit $LASTEXITCODE
    }
}
