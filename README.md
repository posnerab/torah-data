# Torah Data

Torah datasets and a Power BI Desktop project.

Open `T-Projects.pbip` in Power BI Desktop. The report is stored as PBIR under
`T-Projects.Report`, and the semantic model is stored as TMDL under
`T-Projects.SemanticModel`.

The semantic model reads these tracked source workbooks from the public GitHub
repository:

- `Calendar.xlsx`
- `Holidays.xlsx`
- `Torah.xlsx`
- `zmanim.xlsx`
- `Zmanim_Last_Current_Year_Milwaukee.xlsx`

See [scripts/powerbi/README.md](scripts/powerbi/README.md) for the supported
local Power BI modeling, report-authoring, Desktop reload, screenshot, and
data-source credential workflow.
