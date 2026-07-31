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

# Cleanup Script (Windows)
# Stops the PostgreSQL and MySQL containers. The app runs in the foreground, so
# stop it first with Ctrl+C. Pass -RemoveVolumes to also delete the data volumes.

param(
    [switch]$RemoveVolumes
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DatabaseDir = Join-Path $ScriptDir "..\database"

Write-Host "=== Curbside Pickup - Cleanup ==="
Write-Host ""

Push-Location $DatabaseDir
try {
    if ($RemoveVolumes) {
        Write-Host "Removing containers and volumes..."
        docker compose down -v 2>&1 | Write-Host
    } else {
        Write-Host "Removing containers (keeping volumes)..."
        docker compose down 2>&1 | Write-Host
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "=== Cleanup complete! ==="
Write-Host ""
Write-Host "Options:"
Write-Host "  scripts/cleanup.ps1                 # Stop containers, keep data volumes"
Write-Host "  scripts/cleanup.ps1 -RemoveVolumes  # Stop containers and remove data volumes"
