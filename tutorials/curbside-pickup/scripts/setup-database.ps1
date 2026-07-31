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
# Starts PostgreSQL (orders) and MySQL (vehicles) configured for CDC and seeds
# both databases.

# We check $LASTEXITCODE explicitly rather than setting a terminating error
# preference, because the docker CLI writes progress to stderr.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DatabaseDir = Join-Path $ScriptDir "..\database"
$MysqlRootPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "root_admin" }

Write-Host "=== Curbside Pickup - Database Setup ==="
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
    Write-Host "Stopping any existing containers..."
    docker compose down -v 2>&1 | Out-Null

    Write-Host "Starting PostgreSQL and MySQL..."
    docker compose up -d 2>&1 | Write-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: failed to start containers"
        exit 1
    }

    Write-Host "Waiting for PostgreSQL to be ready..."
    for ($i = 1; $i -le 30; $i++) {
        docker exec curbside-pickup-postgres pg_isready -h localhost -U postgres -d RetailOperations 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "PostgreSQL is ready!"; break }
        Write-Host "  Waiting... ($i/30)"; Start-Sleep -Seconds 2
    }

    Write-Host "Waiting for MySQL to be ready..."
    for ($i = 1; $i -le 45; $i++) {
        docker exec curbside-pickup-mysql mysqladmin ping -h localhost -uroot -p"$MysqlRootPassword" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "MySQL is ready!"; break }
        Write-Host "  Waiting... ($i/45)"; Start-Sleep -Seconds 2
    }

    Write-Host ""
    Write-Host "Seeding PostgreSQL (orders)..."
    Get-Content (Join-Path $DatabaseDir "postgres-init.sql") | `
        docker exec -i curbside-pickup-postgres psql -v ON_ERROR_STOP=1 -U postgres -d RetailOperations
    if ($LASTEXITCODE -ne 0) { Write-Host "Error: failed to seed PostgreSQL"; exit 1 }

    Write-Host "Seeding MySQL (vehicles)..."
    Get-Content (Join-Path $DatabaseDir "mysql-init.sql") | `
        docker exec -i curbside-pickup-mysql mysql -uroot -p"$MysqlRootPassword"
    if ($LASTEXITCODE -ne 0) { Write-Host "Error: failed to seed MySQL"; exit 1 }

    Write-Host ""
    Write-Host "=== Database setup complete! ==="
}
finally {
    Pop-Location
}
