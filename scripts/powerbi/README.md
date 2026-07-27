# Power BI automation

This folder provides the supported local workflow for the `T-Projects.pbip`
Power BI Desktop project.

## Architecture

The Microsoft tooling has three separate layers:

| Layer | Tool | Scope |
| --- | --- | --- |
| Semantic model | `powerbi-modeling-mcp` | Read and write the live Desktop Analysis Services/XMLA model |
| Report definition | Microsoft Fabric Power BI report-authoring skill and `powerbi-report-author` | Edit and validate PBIR JSON files |
| Desktop verification | `powerbi-desktop` | Explicitly reload PBIR files and capture rendered PNG screenshots through the local Desktop Bridge |

The Desktop Bridge is not an MCP server. It is a preview JSON-RPC service inside
`PBIDesktop.exe` on the local named pipe
`pbi-desktop-bridge-<process-id>`.

## Setup

Node.js 20 or newer is required by the report-authoring and Desktop Bridge
CLIs.

```powershell
.\scripts\powerbi\Install-PowerBITooling.ps1
```

The setup script:

- installs or updates
  `@microsoft/powerbi-report-authoring-cli@0.1.4` and
  `@microsoft/powerbi-desktop-bridge-cli@0.1.2`;
- registers `@microsoft/powerbi-modeling-mcp@0.5.0-beta.11` in Codex over
  stdio;
- starts the MCP in unattended read/write mode, without its server-side
  confirmation flag;
- sets Codex's server-specific `default_tools_approval_mode` to `approve`, so
  Modeling MCP writes do not pause for client-side approval.

The unattended setting applies to every connection made through
`powerbi-modeling-mcp`; it is not a project-level safety boundary. It does not
weaken approval behavior for other MCP servers. Automation must still discover
and select the exact intended Desktop model before any write.

Restart Codex after registration. The MCP becomes available to new turns; the
report-authoring, report-design, report-planning, and semantic-model-authoring
Fabric skills are installed separately in the Codex skill directory.

In Power BI Desktop, these preview features must be enabled:

1. **Store reports using enhanced metadata format (PBIR)**
2. **Enable external tool access to Power BI Desktop through secure local APIs**

The bridge feature is enabled by default in current Desktop builds. This
project already uses PBIR.

## Live semantic-model verification

Open `T-Projects.pbip`, then run the read-only smoke test:

```powershell
npm --prefix .\scripts\powerbi run test:modeling-mcp
```

The test starts a read-only Modeling MCP session, discovers the local Desktop
XMLA endpoint, connects to the `T-Projects` model, and lists table names. It
does not query table data or modify the model.

To confirm that the unattended registration starts in read/write mode, run:

```powershell
npm --prefix .\scripts\powerbi run test:modeling-mcp:unattended
```

That probe deliberately performs only discovery and list operations. It
confirms the server mode without making a model change, but it does not by
itself exercise a write-time path. During initial setup, a temporary hidden
measure was created, queried, saved, deleted, and saved again through the live
Desktop XMLA endpoint to verify unattended writes and persistence.

Refresh only the live `Zmanim` partition, then run an XMLA calculation pass so
its dependent calculated objects and the small `TODAY()` projections are
current:

```powershell
npm --prefix .\scripts\powerbi run refresh:model
```

The routine command uses a targeted
`partition_operations/RefreshWithXMLA` request followed by
`model_operations/RefreshWithXMLA` with refresh type `Calculate`. It never
submits the 20 immutable tables for data refresh. It requires the Zmanim
web-source credentials and privacy levels to have been saved once in the
Desktop profile. This machine now has Anonymous/Public settings saved for
`raw.githubusercontent.com` and `www.hebcal.com`.

Only migration and recovery validation should deliberately full-refresh every
partition:

```powershell
npm --prefix .\scripts\powerbi run refresh:model:full-migration
```

That command bypasses `excludeFromModelRefresh` by explicitly enumerating every
partition. Do not use it for routine or scheduled Zmanim updates.

Use the registered MCP for semantic-model changes so changes apply to the live
Desktop model. The report-authoring bridge does not replace Modeling MCP for
TMDL/model changes.

## One-time Hebcal compatibility snapshot

Before replacing the workbook-backed `Hebcal` partition, export the exact 87
imported columns from the validated live model:

```powershell
.\scripts\powerbi\Export-HebcalCompatibilitySnapshot.ps1 `
  -DataSource localhost:<port-from-modeling-discovery> `
  -OutputRoot G:\Projects\tmp\hebcal-compatibility-source-v1
```

The exporter:

- reads the imported-column contract from `Hebcal.tmdl`;
- locates the matching local Analysis Services process from the supplied port;
- uses Power BI's local ADOMD client for a read-only, date-ordered DAX export;
- preserves null, empty-string, Boolean, numeric, and DateTime values in typed
  newline-delimited JSON;
- requires exactly 87 imported columns and 18,987 rows; and
- writes through staging and refuses to overwrite an existing snapshot.

This snapshot is validation input for
`scripts\hebcal\materialize_powerbi_compatibility.py`. It does not edit or save
Desktop and does not replace Modeling MCP for model changes.

## One-time static semantic snapshot

The six remaining curated tables are small and effectively immutable:
`Holidays`, `Pasukim`, `Parashiyos`, `Fast Days`, `Haftaros`, and
`Parasha-Mitzvos`. Export their exact imported-column values from the validated
live model to a disposable directory:

```powershell
.\scripts\powerbi\Export-PowerBIStaticSnapshots.ps1 `
  -DataSource localhost:<port-from-modeling-discovery> `
  -OutputRoot G:\Projects\tmp\powerbi-static-source-v1
```

The exporter reads each imported `sourceColumn` contract from TMDL, queries the
live table with a deterministic full-column order, writes typed
newline-delimited JSON, and refuses an existing destination. It is read-only
and does not save or modify Desktop.

Materialize the disposable snapshot as deterministic Parquet:

```powershell
G:\Projects\.venv\Scripts\python.exe `
  scripts\hebcal\materialize_powerbi_static_snapshots.py `
  --snapshot-root G:\Projects\tmp\powerbi-static-source-v1
```

The default immutable destination is `data\powerbi-static-v1`. The builder
verifies the snapshot schema and hashes, preserves the complete 102-column
contract across 6,895 rows, compares each Parquet file to its source with
`EXCEPT ALL` in both directions, writes through staging, and has no overwrite
mode. The JSONL export is disposable after the committed artifact and manifest
have been verified.

Load candidate partitions side by side, require complete DAX comparisons in
both directions, then change only the six existing production partitions.
Refresh each changed partition once and retain `excludeFromModelRefresh` so
Refresh All does not reprocess immutable data.

## PBIR edit, reload, and screenshot loop

```powershell
# Open the Store or MSI Desktop build and discover the bridge.
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Open
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Status

# After each logical PBIR edit batch.
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Validate

# Use the exact PID returned by Status.
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Reload -ProcessId <PID>

# Use a page ID from Status, not its display name.
.\scripts\powerbi\PowerBI-Desktop.ps1 `
  -Action Screenshot `
  -ProcessId <PID> `
  -PageId <PAGE-ID>
```

The wrapper detects the Microsoft Store executable and sets
`PBI_DESKTOP_PATH` for the bridge CLI. Screenshots default to the workspace
evidence folder `..\tmp\powerbi-bridge`, outside this repository.

Before reload, the wrapper checks `hasUnsavedChanges`. It refuses to reload
when Desktop has unsaved UI changes because the bridge has no save operation
and a reload could discard them. Save or discard those changes in Desktop,
rerun `Status`, then reload.

The current report's initial validator baseline is not clean: with
`@microsoft/powerbi-report-authoring-cli` 0.1.4 it reports 12 errors and 32
warnings. Treat that as pre-existing report debt; compare future validation
results to the baseline and fix it in a dedicated report-cleanup change.

## GitHub data-source authentication

`T-Projects.SemanticModel` does not contain a GitHub connector or embedded
GitHub authentication. It uses generic Power Query `Web.Contents` calls to
`raw.githubusercontent.com` in the public `posnerab/torah-data` repository.
The five distinct files currently return HTTP 200 without authentication.

Run the non-secret audit again with:

```powershell
.\scripts\powerbi\Test-GitHubWebSources.ps1
```

The current Microsoft Store profile archive is:

```text
%USERPROFILE%\Microsoft\Power BI Desktop Store App\User.zip
```

The current profile archive contains Power BI's opaque
`Credentials/Credentials.bin` plus its privacy/firewall metadata. The archive
is profile-wide, so the presence of that blob cannot identify its source or
prove which authentication kind it contains. The audit script reports the
archive entry but does not attempt to decrypt or identify its contents. The
GitHub sources were verified separately in Desktop as Anonymous/Public.

Directly injecting a token into `User.zip` is not a supported Power BI API or
file format and is unsafe: credential records are proprietary, encrypted,
version-sensitive, and can be corrupted or leaked through archive backups.

Keep the public sources on Anonymous authentication. If the repository becomes
private:

1. Create a dedicated fine-grained PAT restricted to this repository with
   **Contents: read** and an expiry. Do not reuse the broader `gh` CLI OAuth
   token and do not use an SSH deploy key for HTTPS web requests.
2. Choose one credential store and consumption path:
   - configure a custom Power Query connector through Power BI's credential UI
     and let Power BI manage its separate Key credential; or
   - store the PAT under a Windows-backed `credential_manager` alias such as
     `github:torah-data-powerbi`, then use a pre-refresh staging script that
     retrieves it in-process and downloads source files into an ignored local
     cache.
3. For private GitHub content, use the repository Contents API with
   `Accept: application/vnd.github.raw+json`; do not assume a PAT can be added
   to the existing anonymous `raw.githubusercontent.com` expressions.

There is no supported mechanism to synchronize `credential_manager` directly
into Desktop's `User.zip`. Never hard-code a PAT in TMDL.

## Primary references

- [Power BI Modeling MCP](https://github.com/microsoft/powerbi-modeling-mcp)
- [Microsoft Fabric Skills](https://github.com/microsoft/skills-for-fabric)
- [Power BI Desktop Bridge](https://learn.microsoft.com/power-bi/developer/agentic/power-bi-desktop-bridge-overview)
- [Power BI Desktop projects](https://learn.microsoft.com/power-bi/developer/projects/projects-overview)
- [PBIR report format](https://learn.microsoft.com/power-bi/developer/projects/projects-report)
- [Power Query connector authentication](https://learn.microsoft.com/power-query/connector-authentication)
- [Power Query custom connector authentication](https://learn.microsoft.com/power-query/handling-authentication)
- [GitHub repository contents API](https://docs.github.com/rest/repos/contents)
