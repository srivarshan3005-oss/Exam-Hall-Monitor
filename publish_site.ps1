# Publishes the "site" folder to the gh-pages branch in SMALL batches (one big push gets HTTP 408 from GitHub).
# The site folder keeps its own .git between runs, so later runs upload only what changed.
param([string]$Repo = "https://github.com/srivarshan3005-oss/Exam-Hall-Monitor.git", [int]$Batch = 40)
Set-Location (Join-Path $PSScriptRoot "site")
if (-not (Test-Path ".git")) {
    git init -q
    git checkout -q -b gh-pages
}
git remote remove origin 2>$null
git remote add origin $Repo
git config core.autocrlf false
git config http.postBuffer 524288000
git config http.lowSpeedLimit 0
git config http.lowSpeedTime 999999

$lines = @(git status --porcelain -uall)
if ($lines.Count -eq 0) { Write-Host "Nothing changed since the last publish."; exit 0 }
$paths = @($lines | ForEach-Object { $_.Substring(3).Trim('"') })
Write-Host "Publishing $($paths.Count) changed files in batches of $Batch..."
for ($i = 0; $i -lt $paths.Count; $i += $Batch) {
    $end = [Math]::Min($i + $Batch, $paths.Count) - 1
    git add -- $paths[$i..$end]
    git commit -q -m "Publish files $($i + 1)-$($end + 1) of $($paths.Count)"
    $ok = $false
    for ($try = 1; $try -le 4 -and -not $ok; $try++) {
        $ErrorActionPreference = "Continue"
        git push -f -u origin gh-pages 2>&1 | Out-Host
        if ($LASTEXITCODE -eq 0) { $ok = $true } else { Write-Host "Retry $try of 4 in 5 seconds..."; Start-Sleep -Seconds 5 }
    }
    if (-not $ok) {
        Write-Host "Push failed at file $($i + 1). Run publish_site.bat again - it continues where it stopped."
        exit 1
    }
    Write-Host "Pushed $($end + 1) of $($paths.Count)"
}
exit 0
