# setup_dagent.ps1 — Installs the 'dagent' shortcut globally for both CMD and PowerShell

$ScriptPath = "d:\data_analyse_agent\cli_agent\main.py"
$TargetDir = "d:\data_analyse_agent\cli_agent"
$ProfilePath = $PROFILE

# ── 1. Create dagent.bat for CMD users ─────────────────────────────────────────
$BatPath = Join-Path $TargetDir "dagent.bat"
$BatContent = @"
@echo off
python "$ScriptPath" %*
"@
Set-Content -Path $BatPath -Value $BatContent -Force
Write-Host "Created dagent.bat at $BatPath" -ForegroundColor Green

# ── 2. Add to User PATH for global CMD usage ───────────────────────────────────
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$TargetDir*") {
    $NewPath = $UserPath.TrimEnd(";") + ";" + $TargetDir
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Host "Successfully added $TargetDir to User PATH environment variable!" -ForegroundColor Green
} else {
    Write-Host "$TargetDir is already in User PATH environment variable." -ForegroundColor Yellow
}

# ── 3. Add to PowerShell Profile for fast PowerShell auto-loading ──────────────
$ProfileDir = Split-Path -Parent $ProfilePath
if (-not (Test-Path $ProfileDir)) {
    New-Item -Path $ProfileDir -ItemType Directory -Force | Out-Null
}

if (-not (Test-Path $ProfilePath)) {
    New-Item -Path $ProfilePath -ItemType File -Force | Out-Null
    Write-Host "Created new PowerShell profile at: $ProfilePath" -ForegroundColor Green
}

$FunctionName = "dagent"
$FunctionBody = @"

# DataAgent CLI command shortcut
function $FunctionName {
    python "$ScriptPath" @args
}
"@

$ProfileContent = Get-Content -Path $ProfilePath -Raw
if ($ProfileContent -match "function\s+$FunctionName\s*\{") {
    Write-Host "The '$FunctionName' command is already defined in your PowerShell profile." -ForegroundColor Yellow
} else {
    Add-Content -Path $ProfilePath -Value $FunctionBody
    Write-Host "Successfully added '$FunctionName' command to your PowerShell profile!" -ForegroundColor Green
}

Write-Host "`nTo use 'dagent' globally from any NEW Command Prompt (CMD) or PowerShell window, simply open a new terminal window." -ForegroundColor Cyan
Write-Host "To use it in your current terminal session:" -ForegroundColor Cyan
Write-Host "  CMD: Type 'refreshenv' (if installed) or restart CMD." -ForegroundColor White
Write-Host "  PowerShell: Run '. `$PROFILE'" -ForegroundColor White
