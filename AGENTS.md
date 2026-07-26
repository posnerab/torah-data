# Torah Data Repository Guide

## Scope and precedence

This file governs work inside `G:\Projects\torah-data`. The workspace guide in
`G:\Projects\AGENTS.md` also applies; this file takes precedence where the two
differ.

Before changing the repository, read `README.md`,
`scripts/powerbi/README.md`, and the current Git status. Preserve unrelated
dirty files and never use reset, clean, checkout, or an automatic stash to
erase local work.

## Repository map

- `T-Projects.pbip` is the Power BI Desktop project entry point.
- `T-Projects.SemanticModel/` contains the semantic model in TMDL.
- `T-Projects.Report/` contains the report definition in PBIR.
- `scripts/powerbi/` contains the supported local Power BI automation.
- `G:\Projects\tmp\powerbi-bridge` is the preferred untracked location for
  screenshots and other verification artifacts.

The repository contains only the Power BI project, its source workbooks, and
the supported Power BI automation. Do not reintroduce generated PBIX files,
archived Desktop projects, or a separate R/Shiny publishing workflow.

## Power BI architecture

Treat semantic-model authoring, report authoring, and Desktop verification as
three distinct layers:

| Layer | Supported tool | Boundary |
| --- | --- | --- |
| Semantic model | `powerbi-modeling-mcp` | Live tables, columns, measures, relationships, partitions, DAX, and TMDL metadata |
| Report definition | `powerbi-report-author` and PBIR files | Pages, visuals, filters, bookmarks, navigation, formatting, and validation |
| Desktop verification | `powerbi-desktop` Desktop Bridge CLI | Explicit PBIR reload, state inspection, and rendered screenshots |

The Desktop Bridge is a local JSON-RPC named-pipe service inside
`PBIDesktop.exe`; it is not an MCP server. Its CLI reload is report/PBIR
oriented and currently sends `reloadModelDefinition: false`. Use Modeling MCP
for live model changes.

## Tool setup

Node.js 20 or newer is required by the report and bridge CLIs. Install and
register the pinned tools with:

```powershell
.\scripts\powerbi\Install-PowerBITooling.ps1
```

The pinned versions are:

```text
@microsoft/powerbi-modeling-mcp@0.5.0-beta.11
@microsoft/powerbi-report-authoring-cli@0.1.4
@microsoft/powerbi-desktop-bridge-cli@0.1.2
```

The installer registers Modeling MCP in the user's Codex `config.toml` over
stdio with unattended read/write approval. That approval applies to every
connection made through this MCP server, not just this repository. Always
discover and select the exact `T-Projects` Desktop instance before a write.

Power BI Desktop must have these preview features enabled:

1. Store reports using enhanced metadata format (PBIR).
2. Enable external tool access through secure local APIs.

Restart Codex after changing MCP registration and restart Desktop after
changing preview features.

## Live semantic-model workflow

Power BI Desktop creates a new localhost Analysis Services/XMLA port and model
catalog for each session. Never cache or guess them. Use Modeling MCP
`ListLocalInstances`, match the exact `T-Projects` window, then connect with the
returned connection string.

Read-only and read/write transport probes:

```powershell
npm --prefix .\scripts\powerbi run test:modeling-mcp
npm --prefix .\scripts\powerbi run test:modeling-mcp:unattended
```

The unattended probe starts the server in read/write mode but performs only
reads. It does not independently prove a modifying call. The initial setup was
verified with a temporary hidden measure: create, retrieve, DAX query, save,
delete, save, and confirm the measure was absent.

For model edits:

1. Discover and connect to the exact live Desktop model.
2. Read the target objects before writing.
3. Use transactional MCP batch operations where supported.
4. Verify the result with a Get/List operation and a focused DAX query.
5. Save Desktop with `Ctrl+S`.
6. Poll Desktop Bridge status until `hasUnsavedChanges` is `false`.
7. Disconnect Modeling MCP before inspecting saved TMDL diffs.
8. Confirm no temporary probe objects remain.

Modeling MCP writes change the live model and mark Desktop dirty. The Desktop
Bridge exposes no save method. For unattended Codex work, use Windows app
automation to send `Ctrl+S`; do not ask the user to save unless app automation
is unavailable.

Power BI may add `MCP-PBIModeling` to the model's `PBI_ProTooling` annotation
after MCP authoring. Treat that as expected tooling metadata, but still inspect
every other saved TMDL diff.

## Partition refresh

Refresh all live partitions with:

```powershell
npm --prefix .\scripts\powerbi run refresh:model
```

The command lists the exact partitions and submits a transactional
`RefreshWithXMLA` full refresh with a 20-minute client timeout. Afterward, list
partitions again and require every state to be `Ready`. Also run focused DAX
row counts for important imported tables; a successful command alone is not
enough.

The verified imported-table row counts from the 2026-07-26 setup were:

```text
Zmanim=25
Holidays=98
Pasukim=5863
Parashiyos=61
Hebcal=18987
Fast Days=14
Haftaros=78
Parasha-Mitzvos=781
```

Treat these as a verification snapshot, not permanent assertions. Source data
may legitimately change. The direct MCP all-partition refresh was verified
with all 15 partitions `Ready`; the packaged `refresh:model` wrapper was added
after that live run and should be exercised the next time Desktop is open.

## PBIR edit, reload, and screenshot workflow

Use the wrapper:

```powershell
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Open
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Status
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Validate
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Reload -ProcessId <PID>
.\scripts\powerbi\PowerBI-Desktop.ps1 `
  -Action Screenshot `
  -ProcessId <PID> `
  -PageId <PBIR-PAGE-ID>
```

Before every reload or screenshot:

- Match the process to the exact `T-Projects.pbip` and
  `T-Projects.Report` paths.
- Use a PBIR page ID from Bridge status, not a display name.
- Require `bridgeStatus: connected`.
- Refuse reload when `hasUnsavedChanges` is true; save first.
- Run reload and screenshot operations serially for a given Desktop process.

After each PBIR edit batch:

1. Validate the report.
2. Reload the exact open Desktop instance.
3. Capture every affected page.
4. Inspect the PNG visually for blanks, clipping, overlap, stale values,
   incorrect navigation, and rendering errors.
5. Iterate until the intended state is visible.

The current report has a pre-existing validator baseline of 12 errors and 32
warnings with report-authoring CLI 0.1.4. The known errors are a missing schema
in `definition.pbir` and existing slicer role-cardinality diagnostics. Do not
claim clean validation and do not silently repair this unrelated debt during a
focused report edit. Require the counts not to worsen and reserve cleanup for
a dedicated change.

## GitHub web-source authentication

The semantic model does not contain a GitHub connector or embedded GitHub
credential. It uses generic `Web.Contents` calls to five public files on
`raw.githubusercontent.com`. Audit them without revealing secrets:

```powershell
.\scripts\powerbi\Test-GitHubWebSources.ps1
```

The audit must find at least one GitHub URL, require HTTP 200 anonymously for
all distinct URLs, and report only metadata. It may list entries inside:

```text
%USERPROFILE%\Microsoft\Power BI Desktop Store App\User.zip
```

`User.zip` is a profile-wide, proprietary, encrypted, version-sensitive Power
BI store. The presence of `Credentials/Credentials.bin` does not identify a
GitHub credential or authentication kind. Never decrypt, rewrite, inject a
PAT into, copy, log, or commit this archive.

Keep the current public sources Anonymous with Public privacy levels for
`raw.githubusercontent.com` and `www.hebcal.com`. These settings were saved in
Desktop and a subsequent all-partition refresh completed without prompts.

If the repository becomes private, do not reuse the broad `gh` CLI OAuth token.
Use a dedicated expiring fine-grained PAT with repository Contents read-only,
then choose one supported path:

- Let a custom Power Query connector use a separate Power BI-managed Key
  credential; or
- Store the PAT as a Windows-backed shared credential alias and use an
  ignored, pre-refresh staging process that retrieves it in-process.

For private source retrieval, prefer GitHub's Contents API with
`Accept: application/vnd.github.raw+json`. Never hard-code a PAT, bearer token,
password, or credential-derived value in TMDL, PBIR, scripts, command
arguments, logs, screenshots, or Git.

## Validation before commit

Run the checks relevant to the changed layer:

```powershell
# Parse PowerShell scripts.
$scripts = Get-ChildItem .\scripts\powerbi -File -Filter *.ps1
foreach ($script in $scripts) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $script.FullName,
        [ref]$tokens,
        [ref]$errors
    )
    if ($errors.Count) { throw $errors }
}

node --check .\scripts\powerbi\test-powerbi-modeling-mcp.mjs
.\scripts\powerbi\Test-GitHubWebSources.ps1
powerbi-report-author doctor --pretty
.\scripts\powerbi\PowerBI-Desktop.ps1 -Action Validate
git diff --check
```

When Desktop is open, also run the appropriate Modeling MCP smoke test,
partition/DAX verification, Bridge reload, and screenshot review.

Stage explicit paths in mixed worktrees. Before a requested push, fetch
`origin`, refuse to overwrite incoming commits or a dirty unrelated worktree,
push without force, and verify local `HEAD` equals
`refs/heads/main` on the remote.
