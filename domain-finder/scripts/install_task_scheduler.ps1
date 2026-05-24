param(
  [string]$TaskName = "DomainFinderOrchestrator",
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [int]$IntervalMinutes = 60,
  [switch]$OfflineProbes,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

if ($IntervalMinutes -lt 15) {
  throw "IntervalMinutes must be at least 15. Increase source breadth with better probes, not very frequent polling."
}

$rootPath = (Resolve-Path $Root).Path
$runner = Join-Path $rootPath "scripts\run_orchestrator_loop.ps1"
if (!(Test-Path -LiteralPath $runner)) {
  throw "Runner script not found: $runner"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and !$Force) {
  throw "Scheduled task '$TaskName' already exists. Re-run with -Force to replace it."
}
if ($existing -and $Force) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$arguments = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$runner`"",
  "-Root", "`"$rootPath`""
)
if ($OfflineProbes) {
  $arguments += "-OfflineProbes"
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument ($arguments -join " ") `
  -WorkingDirectory $rootPath

$trigger = New-ScheduledTaskTrigger `
  -Once `
  -At ((Get-Date).AddMinutes(1)) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
  -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Runs Domain Finder orchestrate, deterministic review-jobs, notification digest, and dashboard refresh." | Out-Null

Write-Host "Registered scheduled task '$TaskName' every $IntervalMinutes minutes."
Write-Host "Runner: $runner"
