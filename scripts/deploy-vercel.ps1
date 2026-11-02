<#
.SYNOPSIS
    Deploys candidateSearch to Vercel as one app: the FastAPI backend serves the built frontend.

.DESCRIPTION
    1. Checks the code: backend lint and types, frontend build (full test suites with -Test).
    2. Migrates the production database (DATABASE_URL from the environment, else backend/.env).
    3. Builds the frontend and copies it into backend/frontend_dist for FastAPI to serve.
    4. Checks that the Vercel project has every required environment variable, then deploys
       backend/ to production with the Vercel CLI.
    5. Smoke-tests /health, /ready and the home page on the new deployment.

    First run only: the Vercel CLI asks you to sign in and to link backend/ to a Vercel project.

.PARAMETER Test
    Also run the backend and frontend test suites first (about 4 minutes).

.PARAMETER Yes
    Don't ask before migrating the production database.

.PARAMETER SkipMigrate
    Don't run database migrations (use when you have just run them).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\deploy-vercel.ps1
#>
param(
    [switch]$Test,
    [switch]$Yes,
    [switch]$SkipMigrate
)

$ErrorActionPreference = 'Stop'

# Pinned: a release that has had a few weeks to settle (Vercel needs 48.1.8 or newer).
$VercelCli = 'vercel@63.1.2'

# Every one must be set in the Vercel project (Settings > Environment Variables > Production).
$RequiredEnv = @(
    'ENVIRONMENT',            # production
    'DATABASE_URL',           # postgresql+asyncpg://...neon.tech/neondb?ssl=require (direct host)
    'RATE_LIMIT_KEY_SECRET',  # 32+ random characters
    'OPENAI_API_KEY',
    'RESUMEAI_API_KEY',
    'RESUME_BUCKET',
    'AWS_ENDPOINT_URL_S3',
    'AWS_REGION',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'MAINTENANCE_IN_API',     # false: no background loop on Vercel
    'EMBED_ON_SAVE',          # true: saves embed before answering
    'CRON_SECRET'             # random; Vercel Cron sends it to the maintenance route
)
# Recommended: each function instance opens its own pool, so keep it small.
$RecommendedEnv = @('DB_POOL_SIZE', 'DB_MAX_OVERFLOW')

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
$FrontendDist = Join-Path $Backend 'frontend_dist'

function Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Get-EnvFileValue([string]$Name) {
    $file = Join-Path $Backend '.env'
    if (-not (Test-Path $file)) { return $null }
    $line = Get-Content $file -Encoding UTF8 | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if ($null -eq $line) { return $null }
    return $line.Substring($Name.Length + 1).Trim().Trim('"')
}

if (-not (Test-Path $Python)) { throw "No backend virtual environment at $Python. Create it first (see README)." }
if (-not (Get-Command npx -ErrorAction SilentlyContinue)) { throw 'npx not found: install Node.js.' }

# --- 1. Checks -------------------------------------------------------------------------------
Step 'Checking the backend (ruff, mypy)'
Push-Location $Backend
try {
    Invoke-Checked 'ruff' { & $Python -m ruff check . }
    Invoke-Checked 'mypy' { & $Python -m mypy app }
    if ($Test) {
        Step 'Running the backend tests'
        Invoke-Checked 'pytest' { & $Python -m pytest -q }
    }
} finally { Pop-Location }

Step 'Building the frontend'
Push-Location $Frontend
try {
    Invoke-Checked 'npm ci' { npm ci --no-audit --no-fund }
    if ($Test) {
        Step 'Running the frontend tests'
        Invoke-Checked 'vitest' { npm test }
    }
    Invoke-Checked 'npm run build' { npm run build }
} finally { Pop-Location }

# --- 2. Database migrations --------------------------------------------------------------------
if (-not $SkipMigrate) {
    $databaseUrl = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { Get-EnvFileValue 'DATABASE_URL' }
    if (-not $databaseUrl) { throw 'DATABASE_URL is not set (environment or backend/.env).' }
    $dbHost = ([regex]::Match($databaseUrl, '@([^/:?]+)')).Groups[1].Value
    if ($dbHost -in @('localhost', '127.0.0.1')) {
        throw "DATABASE_URL points at $dbHost. Set `$env:DATABASE_URL to the production database first."
    }
    Step "Migrating the production database on $dbHost"
    if (-not $Yes) {
        $answer = Read-Host "Run 'alembic upgrade head' against $dbHost? (y/N)"
        if ($answer -ne 'y') { throw 'Stopped before migrating.' }
    }
    Push-Location $Backend
    $previous = $env:DATABASE_URL
    try {
        $env:DATABASE_URL = $databaseUrl
        Invoke-Checked 'alembic upgrade' { & $Python -m alembic upgrade head }
    } finally {
        $env:DATABASE_URL = $previous
        Pop-Location
    }
}

# --- 3. Frontend into the backend -------------------------------------------------------------
Step 'Copying the frontend build into backend/frontend_dist'
if (Test-Path $FrontendDist) { Remove-Item -Recurse -Force $FrontendDist }
Copy-Item -Recurse (Join-Path $Frontend 'dist') $FrontendDist

# --- 4. Vercel ---------------------------------------------------------------------------------
Push-Location $Backend
try {
    if (-not (Test-Path (Join-Path $Backend '.vercel\project.json'))) {
        Step 'Linking backend/ to a Vercel project (first run only)'
        Invoke-Checked 'vercel link' { npx --yes $VercelCli link }
    }

    Step 'Checking the Vercel environment variables'
    # stdout only: in Windows PowerShell, redirecting the CLI's stderr banner would throw here.
    $listing = (npx --yes $VercelCli env ls production) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'vercel env ls failed (see the message above).' }
    $missing = @($RequiredEnv | Where-Object { $listing -notmatch "(?m)^\s*$_\s" })
    if ($missing.Count -gt 0) {
        throw ("Set these in Vercel (Settings > Environment Variables > Production), then run again:`n  " +
            ($missing -join "`n  "))
    }
    foreach ($name in $RecommendedEnv) {
        if ($listing -notmatch "(?m)^\s*$name\s") {
            Write-Warning "$name is not set; consider 2 for DB_POOL_SIZE and 3 for DB_MAX_OVERFLOW."
        }
    }

    Step 'Deploying to production'
    $output = npx --yes $VercelCli deploy --prod --yes
    if ($LASTEXITCODE -ne 0) { throw 'vercel deploy failed.' }
    $url = ($output | Where-Object { $_ -match '^https://' } | Select-Object -Last 1)
    if (-not $url) { $url = ($output | Select-Object -Last 1) }
    $url = $url.Trim()
} finally {
    Pop-Location
    # Only the deployment needs it; locally Vite serves the frontend.
    if (Test-Path $FrontendDist) { Remove-Item -Recurse -Force $FrontendDist }
}

# --- 5. Smoke test -----------------------------------------------------------------------------
Step "Smoke-testing $url"
$failed = $false
foreach ($path in @('/health', '/ready', '/')) {
    try {
        $response = Invoke-WebRequest -Uri "$url$path" -UseBasicParsing -TimeoutSec 60
        Write-Host ("  {0,-8} {1}" -f $path, $response.StatusCode) -ForegroundColor Green
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'no answer' }
        Write-Host ("  {0,-8} {1}" -f $path, $status) -ForegroundColor Red
        $failed = $true
    }
}
if ($failed) {
    Write-Warning ("Some checks failed. A 401 means Vercel Deployment Protection is on for this URL: " +
        "open your production domain instead. Otherwise see the function logs in the Vercel dashboard.")
} else {
    Write-Host "`nDeployed: $url" -ForegroundColor Green
}
