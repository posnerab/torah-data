[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$semanticModelPath = Join-Path $repoRoot 'T-Projects.SemanticModel'
$rawPattern = 'https://raw\.githubusercontent\.com/[^"''\s)]+'
$credentialHintPattern = '(?i)(Authorization\s*=|ApiKeyName\s*=|Bearer\s+|github_pat_|gh[opusr]_)'

$tmdlFiles = Get-ChildItem -LiteralPath $semanticModelPath -Recurse -File -Filter '*.tmdl'
$urls = $tmdlFiles |
    Select-String -Pattern $rawPattern -AllMatches |
    ForEach-Object { $_.Matches.Value } |
    Sort-Object -Unique
$embeddedCredentialHints = @(
    $tmdlFiles | Select-String -Pattern $credentialHintPattern
)

$sourceResults = foreach ($url in $urls) {
    try {
        $response = Invoke-WebRequest `
            -Uri $url `
            -Method Head `
            -MaximumRedirection 5 `
            -TimeoutSec 30 `
            -SkipHttpErrorCheck `
            -ErrorAction Stop
        [pscustomobject]@{
            Url = $url
            AnonymousStatusCode = [int]$response.StatusCode
            IsAnonymousSuccess = [int]$response.StatusCode -eq 200
            ErrorType = $null
        }
    }
    catch {
        [pscustomobject]@{
            Url = $url
            AnonymousStatusCode = $null
            IsAnonymousSuccess = $false
            ErrorType = $_.Exception.GetType().FullName
        }
    }
}

$userZipPath = Join-Path $env:USERPROFILE 'Microsoft\Power BI Desktop Store App\User.zip'
$archiveEntries = @()
if (Test-Path -LiteralPath $userZipPath) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($userZipPath)
    try {
        $archiveEntries = @($archive.Entries | ForEach-Object FullName)
    }
    finally {
        $archive.Dispose()
    }
}

$auditResult = [pscustomobject]@{
    SemanticModelPath = $semanticModelPath
    UniqueGitHubSourceCount = @($sourceResults).Count
    AllSourcesAnonymous = @($sourceResults | Where-Object { -not $_.IsAnonymousSuccess }).Count -eq 0
    ModelContainsEmbeddedCredentialHints = $embeddedCredentialHints.Count -gt 0
    Sources = @($sourceResults)
    PowerBIUserZip = if (Test-Path -LiteralPath $userZipPath) { $userZipPath } else { $null }
    UserZipEntries = $archiveEntries
    HasPowerBICredentialStoreEntry = @(
        $archiveEntries | Where-Object { $_ -match '^Credentials/' }
    ).Count -gt 0
    PowerBICredentialStoreIsOpaque = $true
}

$auditResult | ConvertTo-Json -Depth 8
if (-not $auditResult.AllSourcesAnonymous) {
    throw 'One or more GitHub web sources did not return HTTP 200 anonymously.'
}
