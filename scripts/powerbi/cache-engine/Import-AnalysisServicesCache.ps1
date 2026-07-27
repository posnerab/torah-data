param(
    [Parameter(Mandatory)][string]$CachePath,
    [Parameter(Mandatory)][string]$DatabaseName,
    [string]$RuntimeRoot,
    [string]$ServerName = 'localhost\SSAS2025',
    [string]$ServiceName = 'MSOLAP$SSAS2025',
    [string]$ServerBackupPath,
    [switch]$KeepPackage
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CacheEngine.Common.ps1')
$CachePath = [IO.Path]::GetFullPath($CachePath)
$RuntimeRoot = Resolve-CacheEngineRuntimeRoot $RuntimeRoot
if (-not (Test-Path -LiteralPath $CachePath -PathType Leaf)) {
    throw "Cache file not found: $CachePath"
}
if ([string]::IsNullOrWhiteSpace($DatabaseName)) {
    throw 'DatabaseName cannot be empty.'
}

$safeName = ConvertTo-SafeCacheFileName $DatabaseName
$workDirectory = Join-Path $RuntimeRoot 'work'
$backupDirectory = Join-Path $RuntimeRoot 'backups'
New-Item -ItemType Directory -Path $workDirectory, $backupDirectory -Force |
    Out-Null
$packagePath = Join-Path $workDirectory "$safeName.package.pbix"
if ([string]::IsNullOrWhiteSpace($ServerBackupPath)) {
    $ServerBackupPath = Join-Path $backupDirectory "$safeName.server.abf"
}
else {
    $ServerBackupPath = [IO.Path]::GetFullPath($ServerBackupPath)
    New-Item -ItemType Directory -Path (Split-Path -Parent $ServerBackupPath) `
        -Force | Out-Null
}

& (Join-Path $PSScriptRoot 'Start-AnalysisServicesEngine.ps1') `
    -ServiceName $ServiceName -StartupType Automatic | Out-Null

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
if ([IO.File]::Exists($packagePath)) {
    [IO.File]::Delete($packagePath)
}
$file = [IO.File]::Open($packagePath, [IO.FileMode]::CreateNew)
$package = [IO.Compression.ZipArchive]::new(
    $file,
    [IO.Compression.ZipArchiveMode]::Create,
    $false
)
try {
    $contentTypes = $package.CreateEntry('[Content_Types].xml')
    $writer = [IO.StreamWriter]::new(
        $contentTypes.Open(),
        [Text.UTF8Encoding]::new($false)
    )
    try {
        $writer.Write(
            '<?xml version="1.0" encoding="utf-8"?>' +
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
            '<Override PartName="/DataModel" ContentType="application/octet-stream"/>' +
            '</Types>'
        )
    }
    finally {
        $writer.Dispose()
    }
    $part = $package.CreateEntry(
        'DataModel',
        [IO.Compression.CompressionLevel]::NoCompression
    )
    $input = [IO.File]::OpenRead($CachePath)
    $output = $part.Open()
    try {
        $input.CopyTo($output)
    }
    finally {
        $output.Dispose()
        $input.Dispose()
    }
}
finally {
    $package.Dispose()
    $file.Dispose()
}

$conversion = $null
try {
    $existingPid = Get-Content -LiteralPath (
        Join-Path $RuntimeRoot 'conversion-engine.pid'
    ) -ErrorAction SilentlyContinue
    if ($existingPid -and
        (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        & (Join-Path $PSScriptRoot 'Stop-CacheConversionEngine.ps1') `
            -RuntimeRoot $RuntimeRoot
    }
    $conversion = & (Join-Path $PSScriptRoot 'Start-CacheConversionEngine.ps1') `
        -RuntimeRoot $RuntimeRoot
    Import-CacheEngineAmo $RuntimeRoot
    $escapedPackage = [Security.SecurityElement]::Escape($packagePath)
    $escapedDatabase = [Security.SecurityElement]::Escape($DatabaseName)
    $imageLoad = @"
<ImageLoad xmlns="http://schemas.microsoft.com/analysisservices/2003/engine"
  xmlns:ddl100="http://schemas.microsoft.com/analysisservices/2008/engine/100"
  xmlns:ddl700_700="http://schemas.microsoft.com/analysisservices/2018/engine/700/700">
  <ddl700_700:PackagePath>$escapedPackage</ddl700_700:PackagePath>
  <ddl700_700:PackagePartUri>/DataModel</ddl700_700:PackagePartUri>
  <DatabaseName>$escapedDatabase</DatabaseName>
  <DatabaseID>$escapedDatabase</DatabaseID>
  <ddl100:ReadWriteMode>ReadWrite</ddl100:ReadWriteMode>
</ImageLoad>
"@
    Invoke-CacheEngineXmla -ServerName "localhost:$($conversion.Port)" `
        -Xmla $imageLoad

    $escapedBackup = [Security.SecurityElement]::Escape($ServerBackupPath)
    $backup = @"
<Backup xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">
  <Object><DatabaseID>$escapedDatabase</DatabaseID></Object>
  <File>$escapedBackup</File>
  <AllowOverwrite>true</AllowOverwrite>
  <ApplyCompression>true</ApplyCompression>
</Backup>
"@
    Invoke-CacheEngineXmla -ServerName "localhost:$($conversion.Port)" `
        -Xmla $backup

    $restore = @"
<Restore xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">
  <File>$escapedBackup</File>
  <DatabaseName>$escapedDatabase</DatabaseName>
  <AllowOverwrite>true</AllowOverwrite>
</Restore>
"@
    Invoke-CacheEngineXmla -ServerName $ServerName -Xmla $restore

    $server = [Microsoft.AnalysisServices.Tabular.Server]::new()
    try {
        $server.Connect($ServerName)
        $database = $server.Databases[$DatabaseName]
        if (-not $database) {
            throw "Database was not restored: $DatabaseName"
        }
        [pscustomobject]@{
            CachePath = $CachePath
            Server = $ServerName
            Database = $database.Name
            CompatibilityLevel = $database.CompatibilityLevel
            TableCount = $database.Model.Tables.Count
            ServerBackupPath = $ServerBackupPath
        }
    }
    finally {
        if ($server.Connected) {
            $server.Disconnect()
        }
    }
}
finally {
    if ($conversion) {
        & (Join-Path $PSScriptRoot 'Stop-CacheConversionEngine.ps1') `
            -RuntimeRoot $RuntimeRoot
    }
    if (-not $KeepPackage -and [IO.File]::Exists($packagePath)) {
        [IO.File]::Delete($packagePath)
    }
}
