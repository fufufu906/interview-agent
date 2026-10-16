param([switch]$NoBrowser, [switch]$SkipModelPull, [switch]$SkipEmbeddings)
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$projectItem = Get-Item -LiteralPath $projectDir -Force
if ($projectItem.LinkType -eq 'Junction') {
    $projectDir = $projectItem.Target | Select-Object -First 1
}
Set-Location -LiteralPath $projectDir

function Test-DockerReady {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker info --format '{{.OSType}}' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install Docker Desktop with Linux containers first.'
    }
    & docker compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable.' }
    if (-not (Test-DockerReady)) {
        Write-Host 'Starting Docker Desktop...'
        & docker desktop start --detach
        if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop, then run this script again.' }
        $deadline = (Get-Date).AddMinutes(3)
        do {
            Start-Sleep -Seconds 3
            $ready = Test-DockerReady
        } until ($ready -or (Get-Date) -gt $deadline)
        if (-not $ready) { throw 'Docker did not become ready within three minutes.' }
    }
    $dockerOs = & docker info --format '{{.OSType}}'
    if ($dockerOs -ne 'linux') { throw 'Switch Docker Desktop to Linux containers.' }

    if (-not (Test-Path -LiteralPath 'backend\.env' -PathType Leaf)) {
        Copy-Item -LiteralPath 'backend\.env.example' -Destination 'backend\.env'
        Write-Warning 'Created backend/.env. Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL_ID to enable AI generation.'
    }
    New-Item -ItemType Directory -Path 'data\runtime' -Force | Out-Null
    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid.' }
    & docker compose up --build --detach --wait --wait-timeout 180 backend frontend
    if ($LASTEXITCODE -ne 0) { throw 'Container startup failed. Run: docker compose logs --tail 100' }

    # Read the actual published port (also supports MIANSHI_PORT in root .env).
    $binding = & docker compose port frontend 80
    if ($LASTEXITCODE -ne 0) { throw 'Could not determine the frontend port.' }
    $url = 'http://' + ($binding | Select-Object -First 1).Trim()
    $health = Invoke-RestMethod -Uri ($url + '/health') -TimeoutSec 10
    if ($health.status -ne 'ok') { throw 'Application health check failed.' }
    Write-Host "Application ready: $url"
    if (-not $NoBrowser) { Start-Process $url }

    if ($SkipEmbeddings) {
        Write-Warning 'Embedding setup skipped. Retrieval may use lexical fallback.'
        exit 0
    }
    Write-Host 'Starting Ollama (first image download may take several minutes)...'
    & docker compose up --detach --wait --wait-timeout 180 ollama
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Ollama startup failed. The app remains available with lexical retrieval. Run this script again to retry.'
        exit 0
    }

    if (-not $SkipModelPull) {
        Write-Host 'Preparing the embedding model (first download may take several minutes)...'
        # Use the backend's resolved setting so download and retrieval stay aligned.
        $model = & docker compose exec -T backend python -c 'from mianshi_agent.config import get_settings; print(get_settings().memory_embedding_model)'
        if ($LASTEXITCODE -ne 0) { throw 'Could not read the embedding model name.' }
        & docker compose exec -T ollama ollama pull ($model | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Embedding model download failed. The app remains available with lexical retrieval. Run this script again to retry.'
        }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
