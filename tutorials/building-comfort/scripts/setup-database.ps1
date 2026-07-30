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
# building hierarchy (1 Building, 3 Floors, 9 Rooms).

# Note: we deliberately do not set `$ErrorActionPreference = "Stop"` because the
# docker CLI writes progress to stderr, which PowerShell would otherwise treat
# as a terminating error. We check $LASTEXITCODE explicitly instead.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DatabaseDir = Join-Path $ScriptDir "..\database"

Write-Host "=== Building Comfort - Database Setup ==="
Write-Host ""

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Docker is not installed or not in PATH"
    Write-Host "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
}

docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Docker daemon is not running"
    Write-Host "Please start Docker and try again"
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
    $maxRetries = 30
    $ready = $false
    for ($i = 1; $i -le $maxRetries; $i++) {
        docker exec building-comfort-postgres pg_isready -U postgres -d building_comfort 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "PostgreSQL is ready!"
            $ready = $true
            break
        }
        Write-Host "  Waiting... ($i/$maxRetries)"
        Start-Sleep -Seconds 2
    }

    if (-not $ready) {
        Write-Host "Error: PostgreSQL failed to start within the timeout"
        Write-Host "Check logs with: docker logs building-comfort-postgres"
        exit 1
    }

    # Apply the schema and seed data over stdin. We pipe init.sql into psql with
    # `docker exec -i` instead of bind-mounting it into the container, so the same
    # flow works for the dev container, Codespaces, and bare-metal runs.
    Write-Host "Applying schema and seed data..."
    Get-Content (Join-Path $DatabaseDir "init.sql") | `
        docker exec -i building-comfort-postgres psql -v ON_ERROR_STOP=1 -U postgres -d building_comfort
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: failed to apply schema and seed data"
        exit 1
    }

    Write-Host ""
    Write-Host "Seeded rooms:"
    # Pipe the query over stdin to avoid PowerShell mangling the embedded quotes
    # around the case-sensitive "Room" identifier when passing -c to docker.
    'SELECT id, name, temperature, humidity, co2, floor_id FROM "Room" ORDER BY id;' | `
        docker exec -i building-comfort-postgres psql -U drasi_user -d building_comfort

    Write-Host ""
    Write-Host "=== Database setup complete! ==="
    Write-Host ""
    $hostPort = if ($env:POSTGRES_HOST_PORT) { $env:POSTGRES_HOST_PORT } else { "5732" }
    Write-Host "Connection details:"
    Write-Host "  Host: localhost"
    Write-Host "  Port: $hostPort"
    Write-Host "  Database: building_comfort"
    Write-Host "  User: drasi_user"
    Write-Host "  Password: drasi_password"
}
finally {
    Pop-Location
}
