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
regeneration or refresh.

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

No current semantic-model partition or named expression reads these workbooks.
Historical and curated tables load once from committed Parquet artifacts and
remain excluded from Refresh All. The only dynamic import surface is the small
`Zmanim` table, which reads the Hebcal API directly for the API-reported
current Milwaukee date, that date with elevation enabled, one day earlier,
and seven days earlier.

See [scripts/powerbi/README.md](scripts/powerbi/README.md) for the supported
local Power BI modeling, report-authoring, Desktop reload, screenshot, and
data-source credential workflow.

See [scripts/hebcal/README.md](scripts/hebcal/README.md) for the immutable
corpus contract, population, validation, and migration workflow.
