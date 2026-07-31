#!/bin/bash
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

# Add Message Script
# Inserts a message into the feed with a plain SQL INSERT. Drasi's PostgreSQL
# source captures the change via CDC and the console app prints how the queries
# react. There is no application code in the loop -- just SQL.

set -e

CONTAINER="${POSTGRES_CONTAINER:-getting-started-postgres}"
DB="${POSTGRES_DATABASE:-getting_started}"
DB_USER="${POSTGRES_USER:-drasi_user}"

FROM_NAME="${1:-}"
MESSAGE_TEXT="${2:-}"

if [ -z "$FROM_NAME" ] || [ -z "$MESSAGE_TEXT" ]; then
    echo "Usage: $0 <from> <message>"
    echo
    echo "Examples:"
    echo "  $0 'Alice' 'Hello World'      # matches the hello-world-from query"
    echo "  $0 'Bob' 'Goodbye World'      # updates message-count"
    exit 1
fi

# Escape single quotes for safe SQL string literals ('' is an escaped quote).
FROM_SQL="${FROM_NAME//\'/\'\'}"
MESSAGE_SQL="${MESSAGE_TEXT//\'/\'\'}"

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Error: the ${CONTAINER} container is not running."
    echo "Run ./scripts/setup-database.sh first."
    exit 1
fi

echo "Adding message from '$FROM_NAME': $MESSAGE_TEXT"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB" -c \
    "INSERT INTO message (\"from\", message) VALUES ('$FROM_SQL', '$MESSAGE_SQL') RETURNING messageid, \"from\", message;"
