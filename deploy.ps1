# =============================================================================
# deploy.ps1 — Build, push, and deploy Tesco Price Tracker (Windows)
# =============================================================================
# Usage:
#   .\deploy.ps1 [-SkipExtension] [-SkipPush] [-SkipDeploy]
#
# Prerequisites:
#   - Docker Desktop logged in to GHCR (docker login ghcr.io -u <user> -p <PAT>)
#   - SSH configured (OpenSSH for Windows or PuTTY plink)
#   - .env present at project root (GHCR_USERNAME, SSH_HOST, SSH_STACK_PATH)
#   - Node.js + npm installed (for extension build)
# =============================================================================
[CmdletBinding()]
param(
    [switch]$SkipExtension,
    [switch]$SkipPush,
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
Set-Location $ScriptDir

# ── Config defaults ──────────────────────────────────────────────────────────
$GhcrUsername  = "bogat25"
$GhcrPat       = ""
$SshHost       = ""
$SshStackPath  = ""

# Load .env if present
$EnvFile = Join-Path $ScriptDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        if ($_ -match '^([^=]+)=(.*)$') {
            $key   = $Matches[1].Trim()
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            switch ($key) {
                "GHCR_USERNAME"  { $GhcrUsername = $value }
                "GHCR_PAT"       { $GhcrPat = $value }
                "SSH_HOST"       { $SshHost = $value }
                "SSH_STACK_PATH" { $SshStackPath = $value }
            }
        }
    }
}

# Allow env vars to override .env values
if ($env:GHCR_USERNAME)  { $GhcrUsername = $env:GHCR_USERNAME }
if ($env:GHCR_PAT)        { $GhcrPat = $env:GHCR_PAT }
if ($env:SSH_HOST)        { $SshHost = $env:SSH_HOST }
if ($env:SSH_STACK_PATH)  { $SshStackPath = $env:SSH_STACK_PATH }

$BackendImage  = "ghcr.io/$GhcrUsername/tescopricetracker:latest"
$FrontendImage = "ghcr.io/$GhcrUsername/tesco-tracker-frontend:latest"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Tesco Price Tracker — Deploy (PowerShell)"
Write-Host "  Backend image : $BackendImage"
Write-Host "  Frontend image: $FrontendImage"
Write-Host "============================================================" -ForegroundColor Cyan

# ── 0. GHCR login ────────────────────────────────────────────────────────────
if ($GhcrPat) {
    Write-Host ""
    Write-Host "▶  Logging in to GHCR…" -ForegroundColor Yellow
    $GhcrPat | docker login ghcr.io -u $GhcrUsername --password-stdin
    if ($LASTEXITCODE -ne 0) { throw "GHCR login failed" }
    Write-Host "  ✓ Logged in to ghcr.io as $GhcrUsername" -ForegroundColor Green
} else {
    Write-Host "  ℹ  GHCR_PAT not set — assuming already logged in to ghcr.io" -ForegroundColor DarkYellow
}

# ── 1. Build browser extension ───────────────────────────────────────────────
if (-not $SkipExtension) {
    Write-Host ""
    Write-Host "▶  Building browser extension…" -ForegroundColor Yellow
    Push-Location (Join-Path $ScriptDir "extension")
    node build.js
    if ($LASTEXITCODE -ne 0) { throw "Extension build failed" }
    Write-Host "  ✓ Extension packages built (dist/)" -ForegroundColor Green
    Pop-Location
} else {
    Write-Host "  ⏭  Skipping extension build (-SkipExtension)"
}

# ── 2. Build Docker images ───────────────────────────────────────────────────
Write-Host ""
Write-Host "▶  Building backend Docker image…" -ForegroundColor Yellow
docker build --platform linux/amd64 -t $BackendImage $ScriptDir
if ($LASTEXITCODE -ne 0) { throw "Backend Docker build failed" }
Write-Host "  ✓ Backend image built" -ForegroundColor Green

Write-Host ""
Write-Host "▶  Building frontend Docker image…" -ForegroundColor Yellow
docker build --platform linux/amd64 -t $FrontendImage (Join-Path $ScriptDir "frontend")
if ($LASTEXITCODE -ne 0) { throw "Frontend Docker build failed" }
Write-Host "  ✓ Frontend image built" -ForegroundColor Green

# ── 3. Push images to GHCR ──────────────────────────────────────────────────
if (-not $SkipPush) {
    Write-Host ""
    Write-Host "▶  Pushing images to GHCR…" -ForegroundColor Yellow
    docker push $BackendImage
    if ($LASTEXITCODE -ne 0) { throw "Backend image push failed" }
    docker push $FrontendImage
    if ($LASTEXITCODE -ne 0) { throw "Frontend image push failed" }
    Write-Host "  ✓ Images pushed" -ForegroundColor Green
} else {
    Write-Host "  ⏭  Skipping image push (-SkipPush)"
}

# ── 4. Deploy on remote server ───────────────────────────────────────────────
if (-not $SkipDeploy) {
    if (-not $SshHost -or -not $SshStackPath) {
        Write-Host ""
        Write-Host "  ⚠  SSH_HOST or SSH_STACK_PATH not set — skipping remote deploy." -ForegroundColor DarkYellow
        Write-Host "     Add them to your .env:"
        Write-Host "       SSH_HOST=user@server.example.com"
        Write-Host "       SSH_STACK_PATH=/opt/portainer/stacks/tesco-tracker"
    } else {
        Write-Host ""
        Write-Host "▶  Deploying on $SshHost at $SshStackPath…" -ForegroundColor Yellow
        $RemoteCommands = @"
set -e
cd '$SshStackPath'
echo '  -> Pulling new images...'
docker compose pull --quiet
echo '  -> Recreating updated containers...'
docker compose up -d --remove-orphans
echo '  -> Pruning dangling images...'
docker image prune -f --filter 'dangling=true'
echo '  done'
"@
        ssh $SshHost $RemoteCommands
        if ($LASTEXITCODE -ne 0) { throw "Remote deploy failed" }
        Write-Host "  ✓ Remote deploy finished" -ForegroundColor Green
    }
} else {
    Write-Host "  ⏭  Skipping remote deploy (-SkipDeploy)"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  ✅  All done!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
