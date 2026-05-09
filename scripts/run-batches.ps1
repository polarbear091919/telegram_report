<#
.SYNOPSIS
  Safely run N consecutive `langgraph_tagger run` batches with worker-scoped
  recovery on failure.

.DESCRIPTION
  Each iteration generates its own worker_id, passes it to the CLI, and on a
  nonzero exit calls `reset-worker --worker-id <id>` to revert ONLY that
  iteration's stuck rows. Then it sleeps and retries (bounded). This avoids
  the "claim-then-die" failure mode where a crashed CLI leaves rows in
  'processing' indefinitely.

  Retry generates a fresh worker_id every attempt — never reuses an id.

.PARAMETER Iterations
  How many batches to run end-to-end. Default 5.

.PARAMETER BatchSize
  Forwarded to CLI as --batch-size. Omit (0) to use the config default.

.PARAMETER MaxRetries
  Per-iteration retry budget when a run exits nonzero. Default 2 (so an
  iteration tries at most 3 times). After exhaustion the wrapper stops.

.PARAMETER RetrySleepS
  Seconds to wait between retries. Default 3.

.PARAMETER Python
  Path to the venv python.exe. If unset, falls back to $env:LANGGRAPH_PY,
  then auto-discovers .venv near the repo root.

.NOTES
  No timeout is enforced on the child run. PER_ROW_DEADLINE_S already bounds
  per-row LLM calls, and an outer wall-clock timeout that races a still-
  running batch would risk killing healthy work and reverting in-progress
  rows. If the child genuinely hangs, Ctrl+C the wrapper.

.EXAMPLE
  pwsh -File scripts\run-batches.ps1 -Iterations 10 -BatchSize 10
#>
[CmdletBinding()]
param(
    [int]$Iterations = 5,
    [int]$BatchSize = 0,
    [int]$MaxRetries = 2,
    [int]$RetrySleepS = 3,
    [string]$Python = ""
)

# PS 5.1 wraps a native exe's stderr as ErrorRecord; with Stop that makes a
# benign warning abort the wrapper. Use Continue and rely on $LASTEXITCODE.
$ErrorActionPreference = "Continue"

# Resolve worktree root (scripts/run-batches.ps1 → worktree)
$WorktreeRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $WorktreeRoot

# Resolve Python: explicit param > env var > .venv near worktree > main repo .venv
if (-not $Python) { $Python = $env:LANGGRAPH_PY }
if (-not $Python) {
    $cand = Join-Path $WorktreeRoot ".venv\Scripts\python.exe"
    if (Test-Path $cand) { $Python = $cand }
}
if (-not $Python) {
    # Worktree path: <repo>/.claude/worktrees/<name>/ — main repo is 4 levels up
    $cand = Join-Path $WorktreeRoot "..\..\..\.venv\Scripts\python.exe"
    if (Test-Path $cand) { $Python = (Resolve-Path $cand).Path }
}
if (-not $Python -or -not (Test-Path $Python)) {
    Write-Error "Could not locate Python. Pass -Python <path> or set LANGGRAPH_PY."
    exit 2
}

Write-Host "worktree: $WorktreeRoot"
Write-Host "python:   $Python"
Write-Host ""

function New-WorkerId {
    $rand = -join ((48..57) + (97..102) | Get-Random -Count 4 | ForEach-Object { [char]$_ })
    "$($env:COMPUTERNAME)-$PID-$rand"
}

function Invoke-OneRun {
    param([string]$WorkerId)
    $cliArgs = @('-u', '-m', 'langgraph_tagger', 'run', '--worker-id', $WorkerId)
    if ($BatchSize -gt 0) { $cliArgs += @('--batch-size', $BatchSize) }
    # Out-Default routes the child's stdout to the host so the user sees the
    # JSON report; without it, PS would fold that output into the function's
    # own return value and the caller's $ec would become an array.
    & $Python @cliArgs | Out-Default
    return [int]$LASTEXITCODE
}

function Invoke-Cleanup {
    param([string]$WorkerId)
    & $Python -u -m langgraph_tagger reset-worker --worker-id $WorkerId | Out-Default
    return [int]$LASTEXITCODE
}

$totalSuccess = 0
$totalFailedAttempts = 0
$totalResetRows = 0

for ($i = 1; $i -le $Iterations; $i++) {
    Write-Host "=== iteration $i / $Iterations ==="
    $attempt = 0
    $success = $false

    while ($attempt -le $MaxRetries) {
        $workerId = New-WorkerId
        $start = (Get-Date).ToUniversalTime().ToString('HH:mm:ssZ')
        Write-Host "  [attempt $($attempt + 1)] worker_id=$workerId start=$start"
        $ec = Invoke-OneRun -WorkerId $workerId
        $end = (Get-Date).ToUniversalTime().ToString('HH:mm:ssZ')
        Write-Host "  [attempt $($attempt + 1)] end=$end exit=$ec"

        if ($ec -eq 0) { $success = $true; break }

        $totalFailedAttempts++
        Write-Host "  [attempt $($attempt + 1)] FAILED. Cleaning up worker scope..."
        $resetEc = Invoke-Cleanup -WorkerId $workerId
        if ($resetEc -ne 0) {
            Write-Error "  reset-worker itself failed (exit=$resetEc). Aborting wrapper."
            exit 3
        }

        $attempt++
        if ($attempt -le $MaxRetries) {
            Write-Host "  Sleeping ${RetrySleepS}s before retry..."
            Start-Sleep -Seconds $RetrySleepS
        }
    }

    if (-not $success) {
        Write-Host ""
        Write-Host "iteration ${i}: all $($MaxRetries + 1) attempts failed. Stopping."
        Write-Host "Summary: success=$totalSuccess failed_attempts=$totalFailedAttempts"
        exit 1
    }
    $totalSuccess++
}

Write-Host ""
Write-Host "All $Iterations iterations completed."
Write-Host "Summary: success=$totalSuccess failed_attempts=$totalFailedAttempts"
exit 0
