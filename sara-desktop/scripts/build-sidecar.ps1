# Build the Python sidecar executable (Windows PowerShell)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$SidecarDir = Join-Path $ProjectDir "sidecar"

Write-Host "Building Sara Desktop Sidecar..."
Write-Host "Project directory: $ProjectDir"
Write-Host "Sidecar directory: $SidecarDir"

# Check if Python is available
try {
    python --version | Out-Null
} catch {
    Write-Error "Python not found. Please install Python 3."
    exit 1
}

# Create virtual environment if it doesn't exist
$VenvDir = Join-Path $SidecarDir ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..."
    python -m venv $VenvDir
}

# Activate virtual environment
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
& $ActivateScript

# Install dependencies
Write-Host "Installing dependencies..."
pip install -r (Join-Path $SidecarDir "requirements.txt")

# Build with PyInstaller
Write-Host "Building executable..."
Set-Location $SidecarDir
pyinstaller --clean sidecar.spec

# Copy to release location
$DistDir = Join-Path $ProjectDir "release\sidecar"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

Copy-Item (Join-Path $SidecarDir "dist\sidecar.exe") $DistDir

Write-Host "Sidecar built successfully!"
Write-Host "Output: $DistDir"

# Deactivate virtual environment
deactivate
