$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

git config core.hooksPath .githooks

Write-Host "Git hooks path satt til .githooks"
Write-Host "Pre-commit-beskyttelse er aktivert."
Write-Host "Verifiser med: git config --get core.hooksPath"
Write-Host "Hooken kjører automatisk ved git commit."
