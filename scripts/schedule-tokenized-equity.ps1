<#
.SYNOPSIS
    Run the tokenized equity checker once a day via Windows Task Scheduler.

.DESCRIPTION
    Registers a daily task for the current user that runs
    `python -m martin.skills.tokenized_equity` from this repo's .venv and saves a
    dated report to data\tokenized_equity\report-YYYY-MM-DD.txt. Launches not seen
    by an earlier run are marked [NEW]. Output (including failures) is appended to
    data\tokenized_equity\run.log.

    A 7-day look-back is used so filings indexed late are still caught; the
    seen-state keeps them from being flagged [NEW] twice.

.EXAMPLE
    .\scripts\schedule-tokenized-equity.ps1                 # daily at 08:00
    .\scripts\schedule-tokenized-equity.ps1 -Time 07:30
    .\scripts\schedule-tokenized-equity.ps1 -RunNow         # register + run once now
    .\scripts\schedule-tokenized-equity.ps1 -Remove         # unschedule
#>
param(
    [string]$Time = "08:00",
    [int]$Days = 7,
    [switch]$RunNow,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$TaskName = "Martin - Tokenized Equity Daily"
$Repo = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

$Python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "No virtualenv at $Python. Create it first (see README: 'Create the Python environment')."
}

$OutDir = Join-Path $Repo "data\tokenized_equity"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Log = Join-Path $OutDir "run.log"

$Command = "`"$Python`" -m martin.skills.tokenized_equity --days $Days --out `"$OutDir`" >> `"$Log`" 2>&1"
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $Command" -WorkingDirectory $Repo
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
# Catch up after the PC was off/asleep at the scheduled time; needs network.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "Daily scan for tokenized equity launches via regulated entities (Martin)." `
    -Force | Out-Null

Write-Host "Scheduled '$TaskName' daily at $Time."
Write-Host "Reports: $OutDir\report-YYYY-MM-DD.txt   Log: $Log"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started a run now."
}
