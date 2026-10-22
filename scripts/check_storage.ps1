# Read-only preflight for the recovered Windows Docker installation.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

try {
    foreach ($relative in @("data/emergency.encrypted.db", "secrets/database.key")) {
        if (-not (Test-Path -LiteralPath $relative -PathType Leaf)) {
            throw "$relative is missing or is a directory. Keep the existing DB/key; restore the correct file before updating."
        }
        if ((Get-Item -LiteralPath $relative).Length -eq 0) {
            throw "$relative is empty. Restore the correct file; do not generate a replacement key."
        }
    }
    $keyText = [IO.File]::ReadAllText((Resolve-Path "secrets/database.key")).Trim()
    if ($keyText -notmatch '\A[0-9a-fA-F]{64}\z') {
        throw "Key file format is invalid. Restore the original key."
    }
    $keyText = $null
    & docker compose run --rm --build storage-tools verify
    if ($LASTEXITCODE -ne 0) {
        throw "Database/key verification failed. Do not migrate, replace keys, or restart the production container."
    }
    Write-Host "Storage verified. The existing database and key were not replaced."
} catch {
    Write-Error $_
    exit 1
}
