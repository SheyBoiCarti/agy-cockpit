# PowerShell launcher script for Antigravity Cockpit on Windows
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Detect Python executable (.venv preferred)
if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    $Python = "$ScriptDir\.venv\Scripts\python.exe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
} else {
    Write-Error "Python was not found. Please ensure Python is installed and added to PATH."
    exit 1
}

# Ensure static frontend assets exist
$StaticIndex = Join-Path $ScriptDir "agy_cockpit\backend\static\index.html"
if (-not (Test-Path $StaticIndex)) {
    Write-Host "Static frontend assets not found. Building frontend..."
    Push-Location (Join-Path $ScriptDir "agy_cockpit\frontend")
    npm run build
    Pop-Location
}

# Check for workspace parameter in arguments
$hasWs = $args -contains "-w" -or ($args | Where-Object { $_ -like "--workspace*" })
$runArgs = @()
if (-not $hasWs) {
    $runArgs += @("--workspace", $ScriptDir)
}
$runArgs += $args

& $Python -m agy_cockpit.cli @runArgs
