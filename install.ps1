# install.ps1 — DataAgent CLI installer script for Windows

$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $HOME ".dagent\bin"
$ExePath = Join-Path $InstallDir "dagent.exe"
# Update this URL to where the executable release is hosted
$DownloadUrl = "https://github.com/Kovid-Ritesh/data_agent-cli/releases/latest/download/dagent.exe"

Write-Host "Installing DataAgent CLI..." -ForegroundColor Cyan

# Ensure directory exists
if (-not (Test-Path $InstallDir)) {
    New-Item -Path $InstallDir -ItemType Directory -Force | Out-Null
}

# Download executable
Write-Host "Downloading dagent.exe..." -ForegroundColor Gray
try {
    # If the file exists, we try to remove it first to avoid locking
    if (Test-Path $ExePath) {
        Remove-Item -Path $ExePath -Force
    }
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ExePath -UseBasicParsing
    Write-Host "✓ Downloaded dagent.exe successfully." -ForegroundColor Green
} catch {
    Write-Host "⚠ Download could not complete (e.g. if release is not published yet)." -ForegroundColor Yellow
    Write-Host "You can manually copy your built 'dagent.exe' to: $ExePath" -ForegroundColor Gray
}

# Update User PATH variable
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$InstallDir*") {
    $NewPath = $UserPath.TrimEnd(";") + ";" + $InstallDir
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Host "Added $InstallDir to User PATH." -ForegroundColor Green
} else {
    Write-Host "$InstallDir is already in User PATH." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✓ DataAgent v1.0.0 installation sequence completed!" -ForegroundColor Green
Write-Host "To use it, please open a NEW terminal window or run:" -ForegroundColor Cyan
Write-Host "  . `$PROFILE" -ForegroundColor White
Write-Host "Then type 'dagent' to start the agent." -ForegroundColor Cyan
