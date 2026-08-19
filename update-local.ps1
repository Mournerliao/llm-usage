<#
.SYNOPSIS
Sync, collect local usage on Windows, commit raw data, and push it.

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

# Two kinds of files this machine writes but must never carry into a merge:
#
# Artifacts (stats.json / SVG) are owned by GitHub Actions, yet local run.py
# writes them too and generated_at differs every run. Raw is a full re-collect,
# and both machines write the same account-level file. Syncing with either kind
# dirty collides with the remote, and a leftover conflict wedges every later
# run. Both are regenerable, so discarding them is safe.
$ciOwnedPaths = @("data/stats.json", "assets")
$generatedPaths = $ciOwnedPaths + @("data/raw")
$commitMessage = "chore(data): usage raw @ $(Get-Date -Format 'yyyy-MM-dd')"

function Restore-Generated {
    git checkout -f HEAD -- @generatedPaths 2>$null | Out-Null
}

function Restore-CiOwned {
    git checkout -f HEAD -- @ciOwnedPaths 2>$null | Out-Null
}

function Get-UnmergedFiles {
    $raw = git diff --name-only --diff-filter=U
    if ($LASTEXITCODE -ne 0) { throw "git diff failed." }
    if ([string]::IsNullOrWhiteSpace($raw)) { return @() }
    @($raw -split "`n" | Where-Object { $_.Trim().Length -gt 0 })
}

function Invoke-Collect {
    $runArgs = @("run.py")
    if ($Since) { $runArgs += @("--since", $Since) }
    & $pythonCommand @pythonPrefix @runArgs
    if ($LASTEXITCODE -ne 0) { throw "Collection failed with exit code $LASTEXITCODE." }
    # Keep raw only; artifacts go back to HEAD for CI to rebuild.
    Restore-CiOwned
}

function Invoke-CommitRaw {  # $true when a commit was created
    git add data/raw
    if ($LASTEXITCODE -ne 0) { throw "git add failed." }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { return $false }
    if ($LASTEXITCODE -ne 1) { throw "git diff failed." }
    git commit -m $commitMessage
    if ($LASTEXITCODE -ne 0) { throw "git commit failed." }
    return $true
}

# Self-heal whatever a previous conflicted run left behind.
git rebase --abort 2>$null | Out-Null
Restore-Generated
while ($true) {
    $top = git stash list -n 1
    if (-not $top -or $top -notmatch '^stash@\{0\}: autostash$') { break }
    Write-Host "==> Drop leftover autostash"
    git stash drop | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git stash drop failed." }
}
$unmerged = Get-UnmergedFiles
if ($unmerged.Count -gt 0) {
    throw "Unresolved conflicts need manual handling:`n$($unmerged -join "`n")"
}

# Sync before collecting. Raw and artifacts match HEAD at this point, so the
# autostash cannot contain them and cannot collide with the remote.
Write-Host "==> Sync remote"
git pull --rebase --autostash origin main
if ($LASTEXITCODE -ne 0) { throw "git pull failed." }

Write-Host "==> Collect and aggregate"
Invoke-Collect

Write-Host "==> Commit raw data"
if (-not (Invoke-CommitRaw)) {
    Write-Host "No changes; skipping commit."
    exit 0
}

git push origin main
if ($LASTEXITCODE -ne 0) {
    # The remote moved while we were collecting (CI artifacts, or the other
    # machine's raw). No merge needed: raw is a full re-collect, so redoing it
    # on top of the newest remote yields the complete current state.
    Write-Host "==> Push was rejected; re-collect on top of the newest remote"
    git fetch origin main
    if ($LASTEXITCODE -ne 0) { throw "git fetch failed." }

    $ahead = (git rev-list --count FETCH_HEAD..HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "git rev-list failed." }
    $dirty = git status --porcelain -- ':(exclude)data/raw'
    if ($LASTEXITCODE -ne 0) { throw "git status failed." }
    if ($ahead -ne "1" -or -not [string]::IsNullOrWhiteSpace($dirty)) {
        throw "Other unpushed commits or local edits exist; not retrying automatically."
    }

    git reset --hard FETCH_HEAD
    if ($LASTEXITCODE -ne 0) { throw "git reset failed." }
    Invoke-Collect
    if (-not (Invoke-CommitRaw)) {
        Write-Host "No changes; skipping commit."
        exit 0
    }
    git push origin main
    if ($LASTEXITCODE -ne 0) { throw "git push failed." }
}

Write-Host "==> Pushed. GitHub Actions will rebuild stats.json and SVG assets."
