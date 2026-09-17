# Torah Data

Torah datasets and a Power BI Desktop project.

The one-time, location-independent Hebcal corpus for Hebrew years 1 through
6000 is defined and populated by `scripts/hebcal`. Its landed Parquet core is
immutable; later derived transformations and semantic-model relationships may
change without rerunning Hebcal. The independently immutable `powerbi-v1` and
`powerbi-readings-v1` boundaries are likewise loaded once and excluded from
routine refresh. `powerbi-compatibility-v1` is an exact one-time snapshot of
the current wide `Hebcal` table so its partition can be cut over without
rewriting 39 report pages or reproducing legacy workbook quirks. The separate
`powerbi-static-v1` snapshot preserves the six remaining small curated
semantic tables exactly. None of these immutable data products needs scheduled
regeneration or refresh. `zmanim-milwaukee-v1` likewise materializes the
model's usable 1900-03-01 through 29 Elul 6000 Milwaukee date range once.

Open `T-Projects.pbip` in Power BI Desktop. The report is stored as PBIR under
`T-Projects.Report`, and the semantic model is stored as TMDL under
`T-Projects.SemanticModel`.

The repository retains these tracked source workbooks for historical lineage
only:

- `Calendar.xlsx`
- `Holidays.xlsx`
- `Torah.xlsx`
- `zmanim.xlsx`
- `Zmanim_Last_Current_Year_Milwaukee.xlsx`

No current semantic-model partition or named expression reads these workbooks
or the Hebcal API. Historical, curated, and Milwaukee Zmanim tables load once
from committed Parquet artifacts and remain excluded from Refresh All. Report
relative-date filters select today's Zmanim at query time, so advancing the
calendar does not require a semantic-model refresh.

See [scripts/powerbi/README.md](scripts/powerbi/README.md) for the supported
local Power BI modeling, report-authoring, Desktop reload, screenshot, and
data-source credential workflow.

See
[scripts/powerbi/cache-engine/README.md](scripts/powerbi/cache-engine/README.md)
for importing a local `.pbi/cache.abf` into SQL Server 2025 Analysis Services
and running DAX while Power BI Desktop is closed.

See [scripts/hebcal/README.md](scripts/hebcal/README.md) for the immutable
corpus contract, population, validation, and migration workflow.
