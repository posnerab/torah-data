[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^:]+:\d+$')]
    [string]$DataSource,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$TableName = 'Hebcal',

    [string]$TmdlPath = (
        Join-Path $PSScriptRoot '..\..\T-Projects.SemanticModel\definition\tables\Hebcal.tmdl'
    ),

    [string]$AdomdDllPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
    return [System.Convert]::ToHexString($hash).ToLowerInvariant()
}

function ConvertFrom-TmdlIdentifier {
    param([Parameter(Mandatory = $true)][string]$Value)

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("'") -and $trimmed.EndsWith("'")) {
        return $trimmed.Substring(1, $trimmed.Length - 2).Replace("''", "'")
    }
    return $trimmed
}

function Get-ImportedColumnContract {
    param([Parameter(Mandatory = $true)][string]$Path)

    $text = Get-Content -LiteralPath $Path -Raw
    $pattern = '(?ms)^\tcolumn (?<declaration>[^\r\n]+)\r?\n(?<body>.*?)(?=^\t(?:measure|column|hierarchy|partition) |\z)'
    $matches = [System.Text.RegularExpressions.Regex]::Matches($text, $pattern)
    $columns = [System.Collections.Generic.List[object]]::new()

    foreach ($match in $matches) {
        $declaration = $match.Groups['declaration'].Value.Trim()
        $body = $match.Groups['body'].Value
        if ($declaration.Contains(' = ') -or $body -notmatch '(?m)^\s+sourceColumn:\s*(?<source>[^\r\n]+)\s*$') {
            continue
        }

        $sourceColumn = ConvertFrom-TmdlIdentifier $Matches['source']
        if ($body -notmatch '(?m)^\s+dataType:\s*(?<dataType>\S+)\s*$') {
            throw "Imported column '$declaration' has no explicit dataType."
        }

        $columns.Add(
            [ordered]@{
                name = ConvertFrom-TmdlIdentifier $declaration
                source_column = $sourceColumn
                data_type = $Matches['dataType']
            }
        )
    }

    if ($columns.Count -ne 87) {
        throw "Expected 87 imported columns in $Path; found $($columns.Count)."
    }
    if ($columns[0].name -ne 'Date') {
        throw "The first imported column must be Date."
    }
    return $columns
}

function Resolve-AdomdAssembly {
    param(
        [Parameter(Mandatory = $true)][string]$Server,
        [string]$ExplicitPath,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot
    )

    if ($ExplicitPath) {
        $sourcePath = (Resolve-Path -LiteralPath $ExplicitPath).Path
    }
    else {
        $port = [int]($Server -replace '^.*:', '')
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port |
            Select-Object -First 1
        if (-not $listener) {
            throw "No local Analysis Services listener was found on port $port."
        }
        $processPath = (Get-Process -Id $listener.OwningProcess).Path
        $sourcePath = Join-Path (Split-Path -Parent $processPath) 'Microsoft.PowerBI.AdomdClient.dll'
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Power BI ADOMD assembly was not found beside $processPath."
        }
    }

    $assemblyHash = Get-Sha256 $sourcePath
    $runtimePath = Join-Path $RuntimeRoot (
        "Microsoft.PowerBI.AdomdClient-$assemblyHash.dll"
    )
    if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
        Copy-Item -LiteralPath $sourcePath -Destination $runtimePath
    }
    return $runtimePath
}

$resolvedTmdlPath = (Resolve-Path -LiteralPath $TmdlPath).Path
$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $resolvedOutputRoot) {
    throw "$resolvedOutputRoot already exists; compatibility snapshots are immutable."
}

$outputParent = Split-Path -Parent $resolvedOutputRoot
if (-not $outputParent) {
    throw 'OutputRoot must have a parent directory.'
}
[System.IO.Directory]::CreateDirectory($outputParent) | Out-Null

$columns = Get-ImportedColumnContract $resolvedTmdlPath
$tableReference = "'" + $TableName.Replace("'", "''") + "'"
$selectors = foreach ($column in $columns) {
    $alias = $column.name.Replace('"', '""')
    $columnReference = $column.name.Replace(']', ']]')
    "    `"$alias`", $tableReference[$columnReference]"
}
$query = @"
EVALUATE
SELECTCOLUMNS(
    $tableReference,
$($selectors -join ",`n")
)
ORDER BY [Date]
"@

$stagingRoot = Join-Path $outputParent (
    ".{0}-{1}" -f ([System.IO.Path]::GetFileName($resolvedOutputRoot)), [guid]::NewGuid().ToString('N')
)
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'torah-data-adomd-cache'
[System.IO.Directory]::CreateDirectory($stagingRoot) | Out-Null
[System.IO.Directory]::CreateDirectory($runtimeRoot) | Out-Null

$connection = $null
$reader = $null
$writer = $null
try {
    $runtimeAssembly = Resolve-AdomdAssembly `
        -Server $DataSource `
        -ExplicitPath $AdomdDllPath `
        -RuntimeRoot $runtimeRoot
    Add-Type -Path $runtimeAssembly

    $connectionString = "Data Source=$DataSource;Application Name=TorahDataCompatibilitySnapshot"
    $connection = [Microsoft.AnalysisServices.AdomdClient.AdomdConnection]::new(
        $connectionString
    )
    $connection.Open()

    $command = $connection.CreateCommand()
    $command.CommandText = $query
    $command.CommandTimeout = 600
    $reader = $command.ExecuteReader()
    if ($reader.FieldCount -ne $columns.Count) {
        throw "DAX returned $($reader.FieldCount) columns; expected $($columns.Count)."
    }

    for ($index = 0; $index -lt $reader.FieldCount; $index++) {
        $actualName = $reader.GetName($index).Trim('[', ']')
        if ($actualName -ne $columns[$index].name) {
            throw "Column $index is '$actualName'; expected '$($columns[$index].name)'."
        }
    }

    $jsonlPath = Join-Path $stagingRoot 'hebcal_compatibility.jsonl'
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.IO.StreamWriter]::new($jsonlPath, $false, $utf8NoBom)
    $writer.NewLine = "`n"
    $jsonOptions = [System.Text.Json.JsonSerializerOptions]::new()
    $rowCount = 0

    while ($reader.Read()) {
        $row = [ordered]@{}
        for ($index = 0; $index -lt $columns.Count; $index++) {
            $value = $reader.GetValue($index)
            if ($value -is [System.DBNull]) {
                $value = $null
            }
            $row[$columns[$index].name] = $value
        }
        $line = [System.Text.Json.JsonSerializer]::Serialize(
            [object]$row,
            $row.GetType(),
            $jsonOptions
        )
        $writer.WriteLine($line)
        $rowCount++
    }
    $writer.Flush()
    $writer.Dispose()
    $writer = $null
    $reader.Close()
    $reader = $null

    if ($rowCount -ne 18987) {
        throw "Expected 18,987 legacy rows; exported $rowCount."
    }

    $schema = [ordered]@{
        snapshot_version = 'hebcal-compatibility-source-v1'
        table_name = $TableName
        row_count = $rowCount
        columns = $columns
        exporter_script_sha256 = Get-Sha256 $PSCommandPath
        tmdl_sha256 = Get-Sha256 $resolvedTmdlPath
        dax_query_sha256 = Get-TextSha256 $query
    }
    $schemaPath = Join-Path $stagingRoot 'schema.json'
    $schemaJson = $schema | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        $schemaPath,
        $schemaJson + "`n",
        $utf8NoBom
    )

    $provenance = [ordered]@{
        exported_utc = [DateTime]::UtcNow.ToString('o')
        data_source = $DataSource
        database = $connection.Database
        source_jsonl_sha256 = Get-Sha256 $jsonlPath
        schema_sha256 = Get-Sha256 $schemaPath
    }
    $provenancePath = Join-Path $stagingRoot 'provenance.json'
    $provenanceJson = $provenance | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText(
        $provenancePath,
        $provenanceJson + "`n",
        $utf8NoBom
    )

    if (Test-Path -LiteralPath $resolvedOutputRoot) {
        throw "$resolvedOutputRoot appeared during export; refusing to overwrite it."
    }
    Move-Item -LiteralPath $stagingRoot -Destination $resolvedOutputRoot
    Write-Output (Join-Path $resolvedOutputRoot 'schema.json')
}
finally {
    if ($writer) {
        $writer.Dispose()
    }
    if ($reader) {
        $reader.Close()
    }
    if ($connection) {
        $connection.Close()
    }
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
