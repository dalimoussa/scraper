# Bet365 RDP Automated Environment Setup Script
# Run in PowerShell as Administrator

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Bet365 Scraper - Automated RDP Dependencies Installer" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Install Google Chrome
$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ChromePath86 = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

if ((Test-Path $ChromePath) -or (Test-Path $ChromePath86)) {
    Write-Host "[OK] Google Chrome is already installed." -ForegroundColor Green
} else {
    Write-Host "[*] Downloading Google Chrome..." -ForegroundColor Yellow
    $ChromeInstaller = "$env:TEMP\chrome_installer.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://dl.google.com/chrome/install/latest/chrome_installer.exe" -OutFile $ChromeInstaller
        Write-Host "[*] Installing Google Chrome silently..." -ForegroundColor Yellow
        Start-Process -FilePath $ChromeInstaller -ArgumentList "/silent /install" -Wait
        Remove-Item $ChromeInstaller -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Google Chrome installed successfully." -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] Failed to install Chrome: $_" -ForegroundColor Red
    }
}

# 2. Check / Install Python 3.11
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pyVer = python --version
    Write-Host "[OK] Python is already installed: $pyVer" -ForegroundColor Green
} else {
    Write-Host "[*] Downloading Python 3.11..." -ForegroundColor Yellow
    $PyInstaller = "$env:TEMP\python_installer.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $PyInstaller
        Write-Host "[*] Installing Python 3.11 (adding to PATH)..." -ForegroundColor Yellow
        Start-Process -FilePath $PyInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
        Remove-Item $PyInstaller -Force -ErrorAction SilentlyContinue
        
        # Refresh environment PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        Write-Host "[OK] Python 3.11 installed successfully." -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] Failed to install Python: $_" -ForegroundColor Red
    }
}

# 3. Check / Install Git
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "[OK] Git is already installed." -ForegroundColor Green
} else {
    Write-Host "[*] Installing Git via Winget..." -ForegroundColor Yellow
    try {
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements --silent
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        Write-Host "[OK] Git installed." -ForegroundColor Green
    } catch {
        Write-Host "[!] Winget not available, skipping Git auto-install." -ForegroundColor Yellow
    }
}

# 4. Install Python Dependencies
Write-Host "`n[*] Installing project dependencies (pip install -r requirements.txt)..." -ForegroundColor Yellow
try {
    python -m pip install --upgrade pip
    python -m pip install -r "$PSScriptRoot\requirements.txt"
    python -m playwright install chromium
    Write-Host "[OK] All dependencies and Playwright Chromium installed!" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed during pip installation: $_" -ForegroundColor Red
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete! You can now run:" -ForegroundColor Green
Write-Host "    start_server.bat    (or: python server.py)" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
