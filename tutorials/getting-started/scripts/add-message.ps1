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

# Add Message Script (Windows)
# Inserts a message into the feed with a plain SQL INSERT. Drasi captures the
# change via CDC and the console app prints how the queries react.

param(
    [Parameter(Mandatory = $true)][string]$From,
    [Parameter(Mandatory = $true)][string]$Message
)

$Container = if ($env:POSTGRES_CONTAINER) { $env:POSTGRES_CONTAINER } else { "getting-started-postgres" }
$Db = if ($env:POSTGRES_DATABASE) { $env:POSTGRES_DATABASE } else { "getting_started" }
$DbUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "drasi_user" }

# Escape single quotes for safe SQL string literals ('' is an escaped quote).
$FromSql = $From -replace "'", "''"
$MessageSql = $Message -replace "'", "''"

Write-Host "Adding message from '$From': $Message"
$sql = "INSERT INTO message (""from"", message) VALUES ('$FromSql', '$MessageSql') RETURNING messageid, ""from"", message;"
$sql | docker exec -i $Container psql -U $DbUser -d $Db
