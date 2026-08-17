<#
.SYNOPSIS
Install or manage the Windows scheduled task for local usage collection.

.EXAMPLE
.\install-scheduled-task.ps1
.\install-scheduled-task.ps1 -DailyAt 01:00 -RunNow
.\install-scheduled-task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$DailyAt = "00:00",

    [string]$TaskName = "LLM Usage Update",

    [switch]$RunNow,

    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Uninstall) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Scheduled task '$TaskName' is not installed."
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    exit 0
}

$updateScript = Join-Path $PSScriptRoot "update-local.ps1"
if (-not (Test-Path -LiteralPath $updateScript -PathType Leaf)) {
    throw "Update script was not found: $updateScript"
}

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$updateScript`""
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 30) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# InteractiveToken avoids storing a password and lets git reuse the current
# user's credential manager. A missed run starts after the user next signs in.
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Collect local Cursor and Codex usage daily, then push raw data." `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' (daily at $DailyAt)."
Write-Host "Manage it in Task Scheduler (taskschd.msc) or with Get-ScheduledTask."

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started '$TaskName'."
}
