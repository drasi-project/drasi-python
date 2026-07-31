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

# Start Demo Script (Windows)
# Starts (and seeds) the database, then runs the console app in the foreground.
# Leave it running in this terminal; use a second terminal to add and delete
# messages with SQL (docker exec ... psql), as shown in the tutorial. Press
# Ctrl+C to stop, then run scripts/cleanup.ps1.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TutorialDir = Join-Path $ScriptDir ".."

& (Join-Path $ScriptDir "setup-database.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Database setup failed; not starting the app."
    exit 1
}

Write-Host ""
Write-Host "Starting the console app (embeds the Drasi engine)..."
Write-Host "On first run it downloads the Drasi plugins from ghcr.io - give it a moment."
Write-Host ""

Push-Location $TutorialDir
try {
    python app.py
}
finally {
    Pop-Location
}
