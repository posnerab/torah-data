param(
    [Parameter(Mandatory)][string]$RuntimeRoot,
    [string]$InstanceName = 'CacheConversionEngine'
)

$ErrorActionPreference = 'Stop'
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$bin = Join-Path $RuntimeRoot 'bin'
$engine = Join-Path $bin 'msmdsrv.exe'
$data = Join-Path $RuntimeRoot 'workspace\Data'
$enginePidFile = Join-Path $RuntimeRoot 'conversion-engine.pid'
$hostPidFile = Join-Path $RuntimeRoot 'conversion-host.pid'
$portFile = Join-Path $data 'msmdsrv.port.txt'

$PID | Set-Content -LiteralPath $hostPidFile -Encoding ASCII
foreach ($configName in 'msmdsrv.ini', 'msmdsrv.bak') {
    $configPath = Join-Path $data $configName
    if (-not (Test-Path -LiteralPath $configPath)) {
        continue
    }
    $config = Get-Content -LiteralPath $configPath -Raw
    foreach ($element in 'DataDir', 'TempDir', 'LogDir', 'BackupDir',
        'CrashReportsFolder', 'AllowedBrowsingFolders') {
        $config = [regex]::Replace(
            $config,
            "<$element>.*?</$element>",
            "<$element>$data</$element>"
        )
    }
    $config = [regex]::Replace(
        $config,
        '<PrivateProcess>\d+</PrivateProcess>',
        "<PrivateProcess>$PID</PrivateProcess>"
    )
    $config = [regex]::Replace(
        $config,
        '<DisklessModeRequested>\d+</DisklessModeRequested>',
        '<DisklessModeRequested>0</DisklessModeRequested>'
    )
    $config = [regex]::Replace(
        $config,
        '<DeploymentMode>\d+</DeploymentMode>',
        '<DeploymentMode>2</DeploymentMode>'
    )
    $config | Set-Content -LiteralPath $configPath -Encoding Unicode
}

Remove-Item -LiteralPath $portFile -Force -ErrorAction SilentlyContinue
$process = Start-Process -FilePath $engine -WorkingDirectory $bin -ArgumentList @(
    '-c'
    '-n'
    $InstanceName
    '-s'
    "`"$data`""
) -WindowStyle Hidden -PassThru
$process.Id | Set-Content -LiteralPath $enginePidFile -Encoding ASCII

try {
    Wait-Process -Id $process.Id
    $process.Refresh()
    if ($process.ExitCode -ne 0) {
        throw "Conversion engine exited with code $($process.ExitCode)."
    }
}
finally {
    Remove-Item -LiteralPath $enginePidFile, $hostPidFile -Force `
        -ErrorAction SilentlyContinue
}
