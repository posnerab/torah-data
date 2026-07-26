[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$SkipNpmInstall,
    [switch]$SkipMcpRegistration,
    [string]$CodexConfigPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$reportAuthoringPackage = '@microsoft/powerbi-report-authoring-cli@0.1.4'
$desktopBridgePackage = '@microsoft/powerbi-desktop-bridge-cli@0.1.2'
$modelingMcpPackage = '@microsoft/powerbi-modeling-mcp@0.5.0-beta.11'

function Assert-NodeVersion {
    $rawVersion = (& node --version).TrimStart('v')
    if ($LASTEXITCODE -ne 0) {
        throw 'Node.js is required.'
    }

    $nodeVersion = [version]$rawVersion
    if ($nodeVersion.Major -lt 20) {
        throw "Node.js 20 or newer is required by the Power BI report and bridge CLIs. Found $rawVersion."
    }

    Write-Host "Node.js $rawVersion"
}

function Resolve-CodexConfigPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        return [System.IO.Path]::GetFullPath($RequestedPath)
    }

    $codexConfigRoot = if ($env:CODEX_HOME) {
        $env:CODEX_HOME
    } else {
        Join-Path $env:USERPROFILE '.codex'
    }

    return Join-Path $codexConfigRoot 'config.toml'
}

function Set-CodexMcpRegistration {
    param(
        [string]$ConfigPath,
        [string]$Package
    )

    $configDirectory = Split-Path $ConfigPath -Parent
    if (-not (Test-Path -LiteralPath $configDirectory)) {
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    }

    $configText = if (Test-Path -LiteralPath $ConfigPath) {
        [System.IO.File]::ReadAllText($ConfigPath)
    } else {
        ''
    }
    $lineBreak = if ($configText.Contains("`r`n")) { "`r`n" } else { "`n" }
    $sectionHeader = '[mcp_servers.powerbi-modeling-mcp]'
    $sectionText = @(
        $sectionHeader
        'command = "npx"'
        "args = [`"-y`", `"$Package`", `"--start`"]"
        'enabled = true'
        'startup_timeout_sec = 60'
        'tool_timeout_sec = 300'
        'default_tools_approval_mode = "approve"'
        ''
    ) -join $lineBreak

    $sectionStart = $configText.IndexOf(
        $sectionHeader,
        [System.StringComparison]::Ordinal
    )
    if ($sectionStart -ge 0) {
        $sectionContentStart = $sectionStart + $sectionHeader.Length
        $remainingText = $configText.Substring($sectionContentStart)
        $nextSection = [regex]::Match($remainingText, '(?m)^\[')
        $sectionEnd = if ($nextSection.Success) {
            $sectionContentStart + $nextSection.Index
        } else {
            $configText.Length
        }
        $updatedText =
            $configText.Substring(0, $sectionStart) +
            $sectionText +
            $configText.Substring($sectionEnd)
    } else {
        $separator = if ([string]::IsNullOrWhiteSpace($configText)) {
            ''
        } elseif ($configText.EndsWith($lineBreak + $lineBreak)) {
            ''
        } elseif ($configText.EndsWith($lineBreak)) {
            $lineBreak
        } else {
            $lineBreak + $lineBreak
        }
        $updatedText = $configText + $separator + $sectionText
    }

    $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($ConfigPath, $updatedText, $utf8WithoutBom)

    $writtenConfig = [System.IO.File]::ReadAllText($ConfigPath)
    $writtenStart = $writtenConfig.IndexOf(
        $sectionHeader,
        [System.StringComparison]::Ordinal
    )
    $writtenRemainder = $writtenConfig.Substring(
        $writtenStart + $sectionHeader.Length
    )
    $writtenNextSection = [regex]::Match($writtenRemainder, '(?m)^\[')
    $writtenEnd = if ($writtenNextSection.Success) {
        $writtenStart + $sectionHeader.Length + $writtenNextSection.Index
    } else {
        $writtenConfig.Length
    }
    $writtenSection = $writtenConfig.Substring(
        $writtenStart,
        $writtenEnd - $writtenStart
    )
    $requiredPatterns = @(
        '(?m)^command\s*=\s*"npx"\s*$'
        '(?m)^args\s*=\s*\["-y",\s*"@microsoft/powerbi-modeling-mcp@0\.5\.0-beta\.11",\s*"--start"\]\s*$'
        '(?m)^enabled\s*=\s*true\s*$'
        '(?m)^startup_timeout_sec\s*=\s*60\s*$'
        '(?m)^tool_timeout_sec\s*=\s*300\s*$'
        '(?m)^default_tools_approval_mode\s*=\s*"approve"\s*$'
    )
    foreach ($pattern in $requiredPatterns) {
        if ($writtenSection -notmatch $pattern) {
            throw "Codex MCP registration could not be verified in $ConfigPath."
        }
    }
}

Assert-NodeVersion

if (-not $SkipNpmInstall) {
    if ($PSCmdlet.ShouldProcess(
        'global npm tool directory',
        'Install or update the Microsoft Power BI report-authoring and Desktop Bridge CLIs'
    )) {
        & npm.cmd install --global `
            $reportAuthoringPackage `
            $desktopBridgePackage
        if ($LASTEXITCODE -ne 0) {
            throw 'The Power BI CLI installation failed.'
        }
    }
}

& powerbi-report-author --version
if ($LASTEXITCODE -ne 0) {
    throw 'powerbi-report-author is not available.'
}

& powerbi-desktop --version
if ($LASTEXITCODE -ne 0) {
    throw 'powerbi-desktop is not available.'
}

if (-not $SkipMcpRegistration) {
    $configPath = Resolve-CodexConfigPath -RequestedPath $CodexConfigPath
    if ($PSCmdlet.ShouldProcess(
        $configPath,
        'Register Power BI Modeling MCP for unattended read/write operation'
    )) {
        Set-CodexMcpRegistration `
            -ConfigPath $configPath `
            -Package $modelingMcpPackage
        Write-Host "Registered powerbi-modeling-mcp in $configPath"
    }
}

Write-Host 'Power BI tooling is ready. Restart Codex before expecting newly registered MCP tools in an existing session.'
