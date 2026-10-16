$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$projectItem = Get-Item -LiteralPath $projectDir -Force
if ($projectItem.LinkType -eq 'Junction') {
    $projectDir = $projectItem.Target | Select-Object -First 1
}
Set-Location -LiteralPath $projectDir
try {
    & docker compose down
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the application.' }
    Write-Host 'Stopped. Interview data, backend/.env and downloaded models are preserved.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
