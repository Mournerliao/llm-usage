<#
.SYNOPSIS
Collect local usage on Windows, commit raw data, and push it.

.EXAMPLE
.\update-local.ps1
.\update-local.ps1 -Since 2026-07-01
#>
[CmdletBinding()]
param(
    [string]$Since = $env:SINCE
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonCommand = $venvPython
    $pythonPrefix = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonPrefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
    $pythonPrefix = @()
} else {
    throw "Python 3 was not found. Create .venv or install Python 3.12+."
}

Write-Host "==> Collect and aggregate"
$runArgs = @("run.py")
if ($Since) {
    $runArgs += @("--since", $Since)
}
& $pythonCommand @pythonPrefix @runArgs
if ($LASTEXITCODE -ne 0) {
    throw "Collection failed with exit code $LASTEXITCODE."
}

Write-Host "==> Sync remote"
git pull --rebase --autostash origin main
if ($LASTEXITCODE -ne 0) { throw "git pull failed." }

Write-Host "==> Commit raw data"
git add data/raw
if ($LASTEXITCODE -ne 0) { throw "git add failed." }
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "No changes; skipping commit."
    exit 0
}
if ($LASTEXITCODE -ne 1) { throw "git diff failed." }

$date = Get-Date -Format "yyyy-MM-dd"
git commit -m "chore(data): usage raw @ $date"
if ($LASTEXITCODE -ne 0) { throw "git commit failed." }

git push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> Push was rejected; rebase and retry"
    git pull --rebase --autostash origin main
    if ($LASTEXITCODE -ne 0) { throw "git pull failed." }
    git push origin main
    if ($LASTEXITCODE -ne 0) { throw "git push failed." }
}

Write-Host "==> Pushed. GitHub Actions will rebuild stats.json and SVG assets."
