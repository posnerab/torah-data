# Power BI Desktop UI automation

`Save-PowerBIDesktop.ps1` exercises Power BI Desktop's Windows accessibility
tree for the save flow. It targets the exact Desktop process and PBIP reported
by the Desktop Bridge, locates the Save button by AutomationId `save`, requires
the UI Automation `InvokePattern`, invokes it, and polls the bridge until
`hasUnsavedChanges` is false.

It does not use screen coordinates, mouse clicks, SendKeys, window activation,
or title-only process selection.

Inspect the accessibility control without changing state:

```powershell
.\scripts\powerbi\ui_automation\Save-PowerBIDesktop.ps1 `
  -Action Inspect `
  -ProcessId <PID>
```

Save the exact `T-Projects.pbip` instance idempotently:

```powershell
.\scripts\powerbi\ui_automation\Save-PowerBIDesktop.ps1 `
  -Action Save `
  -ProcessId <PID>
```

The Save action returns `AlreadySaved` without invoking the control when the
bridge reports no unsaved changes.
