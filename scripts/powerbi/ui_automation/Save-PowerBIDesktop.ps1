[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Inspect', 'Save')]
    [string]$Action,

    [Parameter(Mandatory)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$ProcessId,

    [string]$ExpectedProjectPath,

    [ValidateRange(1, 60)]
    [int]$WaitSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
if (-not $ExpectedProjectPath) {
    $ExpectedProjectPath = Join-Path $repoRoot 'T-Projects.pbip'
}
$expectedPath = [System.IO.Path]::GetFullPath($ExpectedProjectPath)

function Get-PowerBIBridgeInstance {
    $raw = & powerbi-desktop status --pid $ProcessId --wait-seconds ([string]$WaitSeconds) 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "powerbi-desktop status failed: $($raw -join [Environment]::NewLine)"
    }

    $status = ($raw -join [Environment]::NewLine) | ConvertFrom-Json
    $instance = @($status.instances) |
        Where-Object pid -eq $ProcessId |
        Select-Object -First 1
    if (-not $instance) {
        throw "Power BI Desktop process $ProcessId was not returned by the Desktop Bridge."
    }
    if ($instance.bridgeStatus -ne 'connected') {
        throw "Power BI Desktop process $ProcessId bridge status is '$($instance.bridgeStatus)', not 'connected'."
    }

    $actualPath = [System.IO.Path]::GetFullPath([string]$instance.currentFilePath)
    if (-not [System.StringComparer]::OrdinalIgnoreCase.Equals($actualPath, $expectedPath)) {
        throw "Process $ProcessId has '$actualPath' open; expected '$expectedPath'."
    }

    return $instance
}

function Get-SaveButton {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes

    $process = Get-Process -Id $ProcessId -ErrorAction Stop
    if ($process.ProcessName -ne 'PBIDesktop') {
        throw "Process $ProcessId is '$($process.ProcessName)', not PBIDesktop."
    }
    if ($process.MainWindowHandle -eq [IntPtr]::Zero) {
        throw "Power BI Desktop process $ProcessId has no accessible main window handle."
    }

    $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    if (-not $window) {
        throw "Could not obtain the accessibility root for Power BI Desktop process $ProcessId."
    }

    $automationIdCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
        'save'
    )
    $candidates = $window.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        $automationIdCondition
    )
    $buttons = @(
        $candidates | Where-Object {
            $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button
        }
    )
    if ($buttons.Count -eq 0) {
        throw "No accessible Save button with AutomationId 'save' was found."
    }

    # Desktop can expose duplicate UIA proxies for the same Chrome-hosted
    # control. Accept only duplicates with an identical accessibility
    # fingerprint; refuse multiple distinct Save controls.
    $fingerprints = @(
        $buttons | ForEach-Object {
            $bounds = $_.Current.BoundingRectangle
            '{0}|{1}|{2}|{3}|{4}|{5}|{6}' -f `
                $_.Current.Name,
                $_.Current.LocalizedControlType,
                $_.Current.FrameworkId,
                $bounds.X,
                $bounds.Y,
                $bounds.Width,
                $bounds.Height
        } | Select-Object -Unique
    )
    if ($fingerprints.Count -ne 1) {
        throw "Found $($buttons.Count) Save elements representing $($fingerprints.Count) distinct accessibility controls; refusing to choose one."
    }

    $button = $buttons[0]
    $invokePattern = $null
    $supportsInvoke = $button.TryGetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern,
        [ref]$invokePattern
    )

    return [pscustomobject]@{
        Process = $process
        Button = $button
        InvokePattern = $invokePattern
        SupportsInvoke = $supportsInvoke
        CandidateCount = $buttons.Count
    }
}

$before = Get-PowerBIBridgeInstance
$saveControl = Get-SaveButton
$inspection = [ordered]@{
    processId = $ProcessId
    currentFilePath = [string]$before.currentFilePath
    windowTitle = [string]$saveControl.Process.MainWindowTitle
    automationId = [string]$saveControl.Button.Current.AutomationId
    accessibleName = [string]$saveControl.Button.Current.Name
    controlType = [string]$saveControl.Button.Current.LocalizedControlType
    isEnabled = [bool]$saveControl.Button.Current.IsEnabled
    supportsInvokePattern = [bool]$saveControl.SupportsInvoke
    matchingAccessibilityElements = [int]$saveControl.CandidateCount
    hasUnsavedChangesBefore = [bool]$before.hasUnsavedChanges
}

if ($Action -eq 'Inspect') {
    $inspection.action = 'Inspect'
    $inspection | ConvertTo-Json -Depth 4
    exit 0
}

if (-not $before.hasUnsavedChanges) {
    $inspection.action = 'Save'
    $inspection.invoked = $false
    $inspection.hasUnsavedChangesAfter = $false
    $inspection.result = 'AlreadySaved'
    $inspection | ConvertTo-Json -Depth 4
    exit 0
}
if (-not $saveControl.Button.Current.IsEnabled) {
    throw 'The accessible Save button is disabled while Desktop reports unsaved changes.'
}
if (-not $saveControl.SupportsInvoke -or -not $saveControl.InvokePattern) {
    throw 'The accessible Save button does not support InvokePattern.'
}

$saveControl.InvokePattern.Invoke()
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$after = $null
do {
    try {
        $after = Get-PowerBIBridgeInstance
        if (-not $after.hasUnsavedChanges) {
            break
        }
    }
    catch {
        # Desktop can briefly stop answering bridge requests while it serializes.
        $after = $null
    }
    Start-Sleep -Milliseconds 250
} while ($stopwatch.Elapsed.TotalSeconds -lt $WaitSeconds)

if (-not $after -or $after.hasUnsavedChanges) {
    throw "The Save accessibility action was invoked, but Desktop still reports unsaved changes after $WaitSeconds seconds."
}

$inspection.action = 'Save'
$inspection.invoked = $true
$inspection.hasUnsavedChangesAfter = $false
$inspection.elapsedMilliseconds = [math]::Round($stopwatch.Elapsed.TotalMilliseconds)
$inspection.result = 'Saved'
$inspection | ConvertTo-Json -Depth 4
