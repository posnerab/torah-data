[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^:]+:\d+$')]
    [string]$DataSource,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$TmdlRoot = (
        Join-Path $PSScriptRoot '..\..\T-Projects.SemanticModel\definition\tables'
    ),

    [string]$AdomdDllPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SnapshotVersion = 'powerbi-static-source-v1'
$TargetTableNames = @(
    'Holidays'
    'Pasukim'
    'Parashiyos'
    'Fast Days'
    'Haftaros'
    'Parasha-Mitzvos'
)
$SupportedDataTypes = @(
    'string'
    'int64'
    'double'
    'boolean'
    'dateTime'
)

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

function Get-SnapshotSlug {
    param([Parameter(Mandatory = $true)][string]$TableName)

    $slug = [System.Text.RegularExpressions.Regex]::Replace(
        $TableName.ToLowerInvariant(),
        '[^a-z0-9]+',
        '_'
    ).Trim('_')
    if (-not $slug) {
        throw "Table name '$TableName' has no safe snapshot slug."
    }
    return $slug
}

function Get-ImportedColumnContract {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedTableName
    )

    $text = Get-Content -LiteralPath $Path -Raw
    $tableMatch = [System.Text.RegularExpressions.Regex]::Match(
        $text,
        '(?m)^table\s+(?<name>[^\r\n]+?)\s*$'
    )
    if (-not $tableMatch.Success) {
        throw "$Path has no table declaration."
    }
    $declaredTableName = ConvertFrom-TmdlIdentifier $tableMatch.Groups['name'].Value
    if ($declaredTableName -ne $ExpectedTableName) {
        throw (
            "$Path declares table '$declaredTableName'; " +
            "expected '$ExpectedTableName'."
        )
    }

    $columnPattern = (
        '(?ms)^\tcolumn (?<declaration>[^\r\n]+)\r?\n' +
        '(?<body>.*?)(?=^\t(?:measure|column|hierarchy|partition) |\z)'
    )
    $matches = [System.Text.RegularExpressions.Regex]::Matches(
        $text,
        $columnPattern
    )
    $columns = [System.Collections.Generic.List[object]]::new()
    $seenNames = @{}

    foreach ($match in $matches) {
        $declaration = $match.Groups['declaration'].Value.Trim()
        $body = $match.Groups['body'].Value
        $sourceMatch = [System.Text.RegularExpressions.Regex]::Match(
            $body,
            '(?m)^\s+sourceColumn:\s*(?<source>[^\r\n]+?)\s*$'
        )
        if ($declaration.Contains(' = ') -or -not $sourceMatch.Success) {
            continue
        }

        $dataTypeMatch = [System.Text.RegularExpressions.Regex]::Match(
            $body,
            '(?m)^\s+dataType:\s*(?<dataType>\S+)\s*$'
        )
        if (-not $dataTypeMatch.Success) {
            throw "Imported column '$declaration' has no explicit dataType."
        }

        $columnName = ConvertFrom-TmdlIdentifier $declaration
        $sourceColumn = ConvertFrom-TmdlIdentifier (
            $sourceMatch.Groups['source'].Value
        )
        $dataType = $dataTypeMatch.Groups['dataType'].Value
        if ($SupportedDataTypes -notcontains $dataType) {
            throw (
                "Imported column '$ExpectedTableName[$columnName]' uses " +
                "unsupported dataType '$dataType'."
            )
        }
        if ($seenNames.ContainsKey($columnName)) {
            throw "Table '$ExpectedTableName' has duplicate column '$columnName'."
        }
        $seenNames[$columnName] = $true

        $columns.Add(
            [ordered]@{
                name = $columnName
                source_column = $sourceColumn
                data_type = $dataType
            }
        )
    }

    if ($columns.Count -eq 0) {
        throw "No imported sourceColumn entries were found in $Path."
    }
    return $columns
}

function New-ExportQuery {
    param(
        [Parameter(Mandatory = $true)][string]$TableName,
        [Parameter(Mandatory = $true)][object[]]$Columns
    )

    $tableReference = "'" + $TableName.Replace("'", "''") + "'"
    $selectors = foreach ($column in $Columns) {
        $alias = $column.name.Replace('"', '""')
        $columnReference = $column.name.Replace(']', ']]')
        "    `"$alias`", $tableReference[$columnReference]"
    }
    $orderBy = foreach ($column in $Columns) {
        $columnReference = $column.name.Replace(']', ']]')
        "    [$columnReference] ASC"
    }

    return @"
EVALUATE
SELECTCOLUMNS(
    $tableReference,
$($selectors -join ",`n")
)
ORDER BY
$($orderBy -join ",`n")
"@
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
        $sourcePath = Join-Path (
            Split-Path -Parent $processPath
        ) 'Microsoft.PowerBI.AdomdClient.dll'
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

$resolvedTmdlRoot = (Resolve-Path -LiteralPath $TmdlRoot).Path
$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $resolvedOutputRoot) {
    throw "$resolvedOutputRoot already exists; static snapshots are immutable."
}

$outputParent = Split-Path -Parent $resolvedOutputRoot
if (-not $outputParent) {
    throw 'OutputRoot must have a parent directory.'
}
[System.IO.Directory]::CreateDirectory($outputParent) | Out-Null

$contracts = [ordered]@{}
$slugs = @{}
foreach ($tableName in $TargetTableNames) {
    $tmdlPath = Join-Path $resolvedTmdlRoot "$tableName.tmdl"
    if (-not (Test-Path -LiteralPath $tmdlPath -PathType Leaf)) {
        throw "Target table '$tableName' is missing $tmdlPath."
    }
    $slug = Get-SnapshotSlug $tableName
    if ($slugs.ContainsKey($slug)) {
        throw (
            "Snapshot slug '$slug' collides for '$tableName' and " +
            "'$($slugs[$slug])'."
        )
    }
    $slugs[$slug] = $tableName
    $contracts[$tableName] = [ordered]@{
        slug = $slug
        tmdl_path = $tmdlPath
        columns = @(
            Get-ImportedColumnContract `
                -Path $tmdlPath `
                -ExpectedTableName $tableName
        )
    }
}

$stagingRoot = Join-Path $outputParent (
    ".{0}-{1}" -f (
        [System.IO.Path]::GetFileName($resolvedOutputRoot)
    ), [guid]::NewGuid().ToString('N')
)
$stagingTablesRoot = Join-Path $stagingRoot 'tables'
$runtimeRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) 'torah-data-adomd-cache'
[System.IO.Directory]::CreateDirectory($stagingTablesRoot) | Out-Null
[System.IO.Directory]::CreateDirectory($runtimeRoot) | Out-Null

$connection = $null
try {
    $runtimeAssembly = Resolve-AdomdAssembly `
        -Server $DataSource `
        -ExplicitPath $AdomdDllPath `
        -RuntimeRoot $runtimeRoot
    Add-Type -Path $runtimeAssembly

    $connectionString = (
        "Data Source=$DataSource;" +
        "Application Name=TorahDataStaticSnapshot"
    )
    $connection = [Microsoft.AnalysisServices.AdomdClient.AdomdConnection]::new(
        $connectionString
    )
    $connection.Open()

    $tableSchemas = [ordered]@{}
    $sourceFiles = [ordered]@{}
    $totalRows = 0
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $jsonOptions = [System.Text.Json.JsonSerializerOptions]::new()

    foreach ($tableName in $TargetTableNames) {
        $contract = $contracts[$tableName]
        $columns = @($contract.columns)
        $query = New-ExportQuery -TableName $tableName -Columns $columns
        $relativeSourcePath = "tables/$($contract.slug).jsonl"
        $jsonlPath = Join-Path $stagingTablesRoot "$($contract.slug).jsonl"
        $command = $null
        $reader = $null
        $writer = $null
        try {
            $command = $connection.CreateCommand()
            $command.CommandText = $query
            $command.CommandTimeout = 600
            $reader = $command.ExecuteReader()
            if ($reader.FieldCount -ne $columns.Count) {
                throw (
                    "Table '$tableName' returned $($reader.FieldCount) " +
                    "columns; expected $($columns.Count)."
                )
            }

            for ($index = 0; $index -lt $reader.FieldCount; $index++) {
                $actualName = $reader.GetName($index)
                if (
                    $actualName.StartsWith('[') -and
                    $actualName.EndsWith(']')
                ) {
                    $actualName = $actualName.Substring(
                        1,
                        $actualName.Length - 2
                    ).Replace(']]', ']')
                }
                if ($actualName -ne $columns[$index].name) {
                    throw (
                        "Table '$tableName' column $index is " +
                        "'$actualName'; expected '$($columns[$index].name)'."
                    )
                }
            }

            $writer = [System.IO.StreamWriter]::new(
                $jsonlPath,
                $false,
                $utf8NoBom
            )
            $writer.NewLine = "`n"
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

            if ($rowCount -le 0) {
                throw "Table '$tableName' exported no rows."
            }
            $totalRows += $rowCount
            $tableSchemas[$tableName] = [ordered]@{
                slug = $contract.slug
                source_file = $relativeSourcePath
                row_count = $rowCount
                columns = $columns
                order_by = @($columns | ForEach-Object { $_.name })
                tmdl_sha256 = Get-Sha256 $contract.tmdl_path
                dax_query_sha256 = Get-TextSha256 $query
            }
            $sourceFiles[$relativeSourcePath] = [ordered]@{
                bytes = (Get-Item -LiteralPath $jsonlPath).Length
                sha256 = Get-Sha256 $jsonlPath
                rows = $rowCount
            }
        }
        finally {
            if ($writer) {
                $writer.Dispose()
            }
            if ($reader) {
                $reader.Close()
            }
            if ($command) {
                $command.Dispose()
            }
        }
    }

    $schema = [ordered]@{
        snapshot_version = $SnapshotVersion
        exporter_script_sha256 = Get-Sha256 $PSCommandPath
        table_order = $TargetTableNames
        total_rows = $totalRows
        tables = $tableSchemas
    }
    $schemaPath = Join-Path $stagingRoot 'schema.json'
    $schemaJson = $schema | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText(
        $schemaPath,
        $schemaJson + "`n",
        $utf8NoBom
    )

    $provenance = [ordered]@{
        exported_utc = [DateTime]::UtcNow.ToString('o')
        data_source = $DataSource
        database = $connection.Database
        schema_sha256 = Get-Sha256 $schemaPath
        source_files = $sourceFiles
    }
    $provenancePath = Join-Path $stagingRoot 'provenance.json'
    $provenanceJson = $provenance | ConvertTo-Json -Depth 8
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
    if ($connection) {
        $connection.Close()
    }
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
