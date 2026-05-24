param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [switch]$OfflineProbes,
  [string]$Cargo = "cargo"
)

$ErrorActionPreference = "Stop"

$rootPath = (Resolve-Path $Root).Path
$logDir = Join-Path $rootPath "artifacts\orchestrator\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format "yyyyMMddTHHmmss"
$logPath = Join-Path $logDir "$stamp.log"

function Write-Log {
  param([string]$Message)
  $line = "$(Get-Date -Format o) $Message"
  $line | Tee-Object -FilePath $logPath -Append
}

function Run-Step {
  param(
    [string]$Name,
    [string[]]$Arguments
  )
  Write-Log "START $Name"
  Push-Location $rootPath
  try {
    $stdoutPath = Join-Path $logDir "$stamp.$Name.stdout.tmp"
    $stderrPath = Join-Path $logDir "$stamp.$Name.stderr.tmp"
    $process = Start-Process `
      -FilePath $Cargo `
      -ArgumentList $Arguments `
      -WorkingDirectory $rootPath `
      -NoNewWindow `
      -Wait `
      -PassThru `
      -RedirectStandardOutput $stdoutPath `
      -RedirectStandardError $stderrPath

    foreach ($path in @($stdoutPath, $stderrPath)) {
      if (Test-Path -LiteralPath $path) {
        Get-Content -LiteralPath $path | Tee-Object -FilePath $logPath -Append
        Remove-Item -LiteralPath $path -Force
      }
    }
    if ($process.ExitCode -ne 0) {
      throw "$Name failed with exit code $($process.ExitCode)"
    }
  } finally {
    Pop-Location
  }
  Write-Log "END $Name"
}

$orchestrateArgs = @("run", "--", "orchestrate", "--root", ".", "--once", "--auto")
if ($OfflineProbes) {
  $orchestrateArgs += "--offline-probes"
}

Run-Step "orchestrate" $orchestrateArgs
Run-Step "review-jobs" @("run", "--", "review-jobs", "--root", ".", "--run-approved")
Run-Step "notification-digest" @("run", "--", "notification-digest", "--root", ".")
Run-Step "dashboard" @("run", "--", "dashboard", "--root", ".", "--out", "artifacts/domain_finder/dashboard")

Write-Log "COMPLETE domain-finder unattended loop"
