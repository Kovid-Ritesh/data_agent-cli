@echo off
:: dagent-installer.bat — DataAgent CLI Installer for Windows
:: Sets up the installation directory, downloads the binary, and updates the User PATH.

title DataAgent CLI Installer
color 0B
echo =======================================================================
echo               Welcome to the DataAgent CLI Installer (v1.0.0)
echo =======================================================================
echo.
echo This installer will download the DataAgent standalone executable and
echo register the 'dagent' command globally on your system.
echo.

set "INSTALL_DIR=%USERPROFILE%\.dagent\bin"
set "EXE_PATH=%INSTALL_DIR%\dagent.exe"
set "LOCAL_URL=http://localhost:8000/download/dagent.exe"
set "FALLBACK_URL=https://github.com/your-username/dataagent-cli/releases/latest/download/dagent.exe"

echo [1/3] Creating installation directory...
if not exist "%INSTALL_DIR%" (
    mkdir "%INSTALL_DIR%"
    echo   Created directory: %INSTALL_DIR%
) else (
    echo   Directory already exists: %INSTALL_DIR%
)
echo.

echo [2/3] Downloading dagent.exe...
:: Try local server first
echo   Attempting to download from local server (%LOCAL_URL%)...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { (New-Object System.Net.WebClient).DownloadFile('%LOCAL_URL%', '%EXE_PATH%'); Write-Host '  ✓ Successfully downloaded from local server.' -ForegroundColor Green } catch { throw }" 2>nul

if not exist "%EXE_PATH%" (
    echo   Local server download unavailable. Attempting fallback URL (%FALLBACK_URL%)...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { (New-Object System.Net.WebClient).DownloadFile('%FALLBACK_URL%', '%EXE_PATH%'); Write-Host '  ✓ Successfully downloaded from fallback URL.' -ForegroundColor Green } catch { Write-Host '  ✗ Fallback download failed.' -ForegroundColor Red }"
)

if not exist "%EXE_PATH%" (
    echo.
    echo [ERROR] Could not download dagent.exe.
    echo Please make sure the local server is running, or download it manually and place it in:
    echo   %EXE_PATH%
    echo.
    goto end
)

echo.
echo [3/3] Registering PATH environment variable...
powershell -Command "$userPath = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($userPath -notlike '*%INSTALL_DIR%*') { $newPath = $userPath.TrimEnd(';') + ';%INSTALL_DIR%'; [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'); Write-Host '  ✓ Added DataAgent to User PATH environment variable.' -ForegroundColor Green } else { Write-Host '  ✓ DataAgent is already registered in User PATH.' -ForegroundColor Yellow }"

echo.
echo =======================================================================
echo                       Installation Successful!
echo =======================================================================
echo.
echo You can now use the 'dagent' command globally from any NEW command prompt.
echo.
echo Try opening a new terminal and typing:
echo   dagent
echo.
echo =======================================================================

:end
echo Press any key to exit.
pause >nul
