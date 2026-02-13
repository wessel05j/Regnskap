$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonLauncher = "py -3.11"
    try {
        & py -3.11 --version | Out-Null
    } catch {
        $pythonLauncher = "py -3"
    }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonLauncher = "python"
} else {
    Write-Host "Fant ikke Python. Installer Python 3.11+ og prover igjen."
    exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Oppretter virtuelt miljo (.venv)..."
    Invoke-Expression "$pythonLauncher -m venv .venv"
}

& ".venv\Scripts\Activate.ps1"

try {
    python -c "import fastapi,uvicorn,jinja2,pydantic,reportlab,multipart" | Out-Null
} catch {
    Write-Host "Installerer avhengigheter..."
    python -m pip install --upgrade pip
    pip install -r requirements.txt
}

Start-Process "http://127.0.0.1:8000"
Write-Host "Starter server pa http://127.0.0.1:8000 ..."
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
