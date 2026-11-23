$ErrorActionPreference = 'Stop'
$envFile = Join-Path $PSScriptRoot '..\backend\.env'
$envFile = [IO.Path]::GetFullPath($envFile)
if (-not (Test-Path $envFile)) { throw "Configuration file missing: $envFile" }
$lines = [Collections.Generic.List[string]]::new()
Get-Content -LiteralPath $envFile | ForEach-Object { $lines.Add($_) }
function Set-EnvValue([string]$Name, [string]$Value) {
  $prefix = "$Name="
  $found = $false
  for ($i=0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].StartsWith($prefix)) { $lines[$i] = $prefix + $Value; $found = $true; break }
  }
  if (-not $found) { $lines.Add($prefix + $Value) }
}
Write-Host "`nExam Monitor Ultimate - first-run configuration" -ForegroundColor Cyan
$college = Read-Host "College/institution display name (Enter keeps current setting)"
if (-not [string]::IsNullOrWhiteSpace($college)) { Set-EnvValue "COLLEGE_NAME" $college.Trim() }
Write-Host "Local Windows setup uses SQLite by default; existing DATABASE_URL is preserved."
Write-Host "Do not paste passwords or API keys into this wizard."
[IO.File]::WriteAllLines($envFile, $lines, [Text.UTF8Encoding]::new($false))
try {
  $acl = Get-Acl -LiteralPath $envFile
  $acl.SetAccessRuleProtection($true, $false)
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  $acl.SetAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($identity,"FullControl","Allow")))
  $acl.SetAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("SYSTEM","FullControl","Allow")))
  Set-Acl -LiteralPath $envFile -AclObject $acl
} catch { Write-Warning "Could not tighten .env ACL automatically: $($_.Exception.Message). Restrict it manually to the current user and SYSTEM." }
Write-Host "Configuration saved to backend\.env" -ForegroundColor Green
