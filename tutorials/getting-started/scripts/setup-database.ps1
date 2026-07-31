# Copyright 2026 The Drasi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Setup Database Script (Windows)
# Starts PostgreSQL with logical replication (WAL) enabled for CDC and seeds the
# message feed.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DatabaseDir = Join-Path $ScriptDir "..\database"

Write-Host "=== Getting Started - Database Setup ==="
Write-Host ""

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Docker is not installed or not in PATH"
    exit 1
}

docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Docker daemon is not running"
    exit 1
}

Push-Location $DatabaseDir
try {
    Write-Host "Stopping any existing PostgreSQL container..."
    docker compose down -v 2>&1 | Out-Null

    Write-Host "Starting PostgreSQL with WAL replication..."
    docker compose up -d 2>&1 | Write-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: failed to start PostgreSQL container"
        exit 1
    }

    Write-Host "Waiting for PostgreSQL to be ready..."
    $pgReady = $false
    for ($i = 1; $i -le 30; $i++) {
        docker exec getting-started-postgres pg_isready -h localhost -U postgres -d getting_started 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "PostgreSQL is ready!"; $pgReady = $true; break }
        Write-Host "  Waiting... ($i/30)"; Start-Sleep -Seconds 2
    }
    if (-not $pgReady) {
        Write-Host "Error: PostgreSQL did not become ready within the timeout."
        Write-Host "Check logs with: docker logs getting-started-postgres"
        exit 1
    }

    Write-Host ""
    Write-Host "Applying schema and seed data..."
    Get-Content (Join-Path $DatabaseDir "init.sql") | `
        docker exec -i getting-started-postgres psql -v ON_ERROR_STOP=1 -U postgres -d getting_started
    if ($LASTEXITCODE -ne 0) { Write-Host "Error: failed to apply schema and seed data"; exit 1 }

    Write-Host ""
    Write-Host "Seeded messages:"
    'SELECT messageid, sender, message FROM message ORDER BY messageid;' | `
        docker exec -i getting-started-postgres psql -U drasi_user -d getting_started

    Write-Host ""
    Write-Host "=== Database setup complete! ==="
}
finally {
    Pop-Location
}
