# Offline Power BI cache query engine

These scripts load a Power BI Desktop project `cache.abf` into a normal SQL
Server 2025 Analysis Services Tabular instance. Once imported, Power BI
Desktop and the temporary conversion engine are not required for queries.

## How it works

Power BI Desktop's `.pbi/cache.abf` is an Analysis Services image, but it is
not directly accepted by the normal server `Restore` command. The importer:

1. wraps `cache.abf` as the `/DataModel` part of a temporary package;
2. starts a copied Power BI Analysis Services engine as an elevated,
   short-lived conversion process;
3. loads the image with `ImageLoad`;
4. creates a genuine Analysis Services server backup;
5. restores that backup into SQL Server 2025 Analysis Services; and
6. stops the conversion engine in a `finally` block.

The resulting database is served by the ordinary Windows Analysis Services
service and can be queried from DAX Studio, SSMS, AMO, ADOMD.NET, or Modeling
MCP.

## Prerequisites

- Windows PowerShell 5.1 or PowerShell 7.
- SQL Server 2025 Analysis Services installed in Tabular mode.
- The Windows user listed as an Analysis Services administrator.
- A prepared runtime directory containing:

```text
<runtime>\
  bin\msmdsrv.exe
  workspace\Data\msmdsrv.ini
  workspace\Data\msmdsrv.bak
  clients\amo\Microsoft.AnalysisServices.Core.dll
  clients\amo\Microsoft.AnalysisServices.Tabular.dll
  clients\adomd\Microsoft.AnalysisServices.AdomdClient.dll
```

`bin` and the workspace configuration must come from the same installed Power
BI Desktop engine version. The runtime is machine-local and must not be
committed. This machine's prepared runtime is:

```text
G:\Tools\AnalysisServicesCacheEngine
```

For convenience:

```powershell
$env:AS_CACHE_ENGINE_RUNTIME_ROOT = 'G:\Tools\AnalysisServicesCacheEngine'
```

Every script also accepts `-RuntimeRoot` explicitly, which is preferred in
automation.

## Start and inspect the normal engine

The helper elevates through UAC when service control requires it:

```powershell
.\scripts\powerbi\cache-engine\Start-AnalysisServicesEngine.ps1 `
  -ServiceName 'MSOLAP$SSAS2025'
```

Inspect the service and restored databases:

```powershell
.\scripts\powerbi\cache-engine\Get-AnalysisServicesEngineStatus.ps1 `
  -RuntimeRoot G:\Tools\AnalysisServicesCacheEngine
```

Default endpoint:

```text
Data Source: localhost\SSAS2025
```

## Import any cache

Power BI Desktop must be closed if another process could still be writing the
cache. The importer reads the cache but never edits it.

```powershell
.\scripts\powerbi\cache-engine\Import-AnalysisServicesCache.ps1 `
  -CachePath G:\Projects\torah-data\T-Projects.SemanticModel\.pbi\cache.abf `
  -DatabaseName TorahOffline `
  -RuntimeRoot G:\Tools\AnalysisServicesCacheEngine
```

Override the defaults for a different named instance:

```powershell
.\scripts\powerbi\cache-engine\Import-AnalysisServicesCache.ps1 `
  -CachePath D:\Models\Sales.SemanticModel\.pbi\cache.abf `
  -DatabaseName SalesOffline `
  -RuntimeRoot G:\Tools\AnalysisServicesCacheEngine `
  -ServerName 'localhost\TABULAR2025' `
  -ServiceName 'MSOLAP$TABULAR2025'
```

The server-format backup is retained under `<runtime>\backups` so the database
can be restored again without repeating `ImageLoad`. The temporary package is
deleted unless `-KeepPackage` is supplied.

Re-running the command with the same database name replaces that database with
the data baked into the specified cache.

## Run DAX

Inline query:

```powershell
$dax = @'
EVALUATE
ROW(
    "Rows", COUNTROWS('Hebcal'),
    "FirstDate", MIN('Hebcal'[Date]),
    "LastDate", MAX('Hebcal'[Date])
)
'@

.\scripts\powerbi\cache-engine\Invoke-AnalysisServicesDax.ps1 `
  -DatabaseName TorahOffline `
  -RuntimeRoot G:\Tools\AnalysisServicesCacheEngine `
  -Dax $dax
```

Query file:

```powershell
.\scripts\powerbi\cache-engine\Invoke-AnalysisServicesDax.ps1 `
  -DatabaseName TorahOffline `
  -RuntimeRoot G:\Tools\AnalysisServicesCacheEngine `
  -DaxFile .\query.dax |
  Export-Csv .\query-results.csv -NoTypeInformation
```

The default row limit is 10,000. Increase it deliberately with `-MaxRows`.

External tools can connect directly with:

```text
Server:   localhost\SSAS2025
Database: <DatabaseName supplied during import>
Auth:     Windows integrated security
```

## Stop the service

Stopping the normal service disconnects all query clients:

```powershell
.\scripts\powerbi\cache-engine\Stop-AnalysisServicesEngine.ps1 `
  -ServiceName 'MSOLAP$SSAS2025'
```

Add `-SetManual` to prevent automatic startup. The importer normally leaves
the service running and configured for automatic startup.

## Troubleshooting

- **`Restore` rejects `cache.abf`**: do not restore the Desktop cache
  directly. Use `Import-AnalysisServicesCache.ps1`.
- **UAC prompt**: expected when starting the conversion engine or controlling
  the Windows service.
- **Compatibility level 1606**: SQL Server 2025 Analysis Services accepts the
  converted server backup without rewriting the level.
- **Conversion engine remains running after a failure**: run
  `Stop-CacheConversionEngine.ps1 -RuntimeRoot <runtime>`.
- **AMO or ADOMD load failure**: verify the client DLLs in the runtime match
  the installed package and run the public scripts from PowerShell 7.
- **The SQL service cannot read the backup**: grant its service identity read
  access to the selected backup directory, or keep backups under the prepared
  runtime directory where access has already been validated.
- **Database is stale**: rerun the importer after Power BI Desktop has
  finished saving the cache, then query the fixed SQL AS endpoint.

Generated packages, backups, logs, PID files, and the runtime binaries belong
outside Git.
