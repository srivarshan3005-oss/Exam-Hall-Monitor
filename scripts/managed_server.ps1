# Exact, safe handling of the PID file written by start.bat.
# check: exit 0 only if the PID is a live python process whose command line is THIS application's uvicorn server.
# stop : terminates that process tree only when it passes the same check; a stale or reused PID is never killed.
param(
  [Parameter(Mandatory = $true)][ValidateSet('check', 'stop')][string]$Action,
  [Parameter(Mandatory = $true)][string]$PidFile
)
$ErrorActionPreference = 'Stop'
function Get-ManagedProcess {
  if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
  $raw = Get-Content -LiteralPath $PidFile -TotalCount 1
  if ($null -eq $raw) { return $null }
  $raw = ([string]$raw).Trim()
  if ($raw -notmatch '^\d+$') { return $null }
  $proc = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId=" + [int]$raw) -ErrorAction SilentlyContinue
  if (-not $proc) { return $null }
  if ($proc.Name -notmatch '^pythonw?\.exe$') { return $null }
  if (($proc.CommandLine -notmatch 'uvicorn') -or ($proc.CommandLine -notmatch 'app\.main:app')) { return $null }
  return $proc
}
$managed = Get-ManagedProcess
if ($Action -eq 'check') { if ($managed) { exit 0 } else { exit 1 } }
if ($managed) {
  & taskkill.exe /PID $managed.ProcessId /T /F | Out-Null
  Write-Host ("Stopped managed server process " + $managed.ProcessId)
} else {
  Write-Host "PID file is stale or does not belong to this application; no process was stopped."
}
exit 0
