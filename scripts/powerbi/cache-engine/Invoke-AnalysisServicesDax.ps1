param(
    [Parameter(Mandatory)][string]$DatabaseName,
    [string]$RuntimeRoot,
    [string]$ServerName = 'localhost\SSAS2025',
    [string]$Dax,
    [string]$DaxFile,
    [ValidateRange(1, 1000000)][int]$MaxRows = 10000
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CacheEngine.Common.ps1')
$RuntimeRoot = Resolve-CacheEngineRuntimeRoot $RuntimeRoot
if ([string]::IsNullOrWhiteSpace($Dax) -eq
    [string]::IsNullOrWhiteSpace($DaxFile)) {
    throw 'Specify exactly one of -Dax or -DaxFile.'
}
if ($DaxFile) {
    $Dax = Get-Content -LiteralPath ([IO.Path]::GetFullPath($DaxFile)) -Raw
}

$client = Join-Path $RuntimeRoot `
    'clients\adomd\Microsoft.AnalysisServices.AdomdClient.dll'
if (-not ('Microsoft.AnalysisServices.AdomdClient.AdomdConnection' -as [type])) {
    Add-Type -Path $client
}
$connectionString = "Data Source=$ServerName;Initial Catalog=$DatabaseName;" +
    'Integrated Security=SSPI'
$connection =
    [Microsoft.AnalysisServices.AdomdClient.AdomdConnection]::new(
        $connectionString
    )
$reader = $null
try {
    $connection.Open()
    $command = $connection.CreateCommand()
    $command.CommandText = $Dax
    $reader = $command.ExecuteReader()
    $rowCount = 0
    while ($reader.Read()) {
        $rowCount++
        if ($rowCount -gt $MaxRows) {
            throw "Query exceeded MaxRows=$MaxRows."
        }
        $row = [ordered]@{}
        for ($index = 0; $index -lt $reader.FieldCount; $index++) {
            $row[$reader.GetName($index)] = if ($reader.IsDBNull($index)) {
                $null
            }
            else {
                $reader.GetValue($index)
            }
        }
        [pscustomobject]$row
    }
}
finally {
    if ($reader) {
        $reader.Dispose()
    }
    $connection.Dispose()
}
