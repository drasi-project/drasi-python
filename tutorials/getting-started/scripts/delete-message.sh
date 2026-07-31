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

# Delete Message Script
# Deletes a message by id with a plain SQL DELETE. Drasi captures the change via
# CDC and the console app prints how the queries react.

set -e

CONTAINER="${POSTGRES_CONTAINER:-getting-started-postgres}"
DB="${POSTGRES_DATABASE:-getting_started}"
DB_USER="${POSTGRES_USER:-drasi_user}"

MESSAGE_ID="${1:-}"

if [ -z "$MESSAGE_ID" ]; then
    echo "Usage: $0 <messageid>"
    echo
    echo "Tip: run 'docker exec $CONTAINER psql -U $DB_USER -d $DB -c \"SELECT messageid, \\\"from\\\", message FROM message;\"' to list ids."
    exit 1
fi

if ! printf '%s' "$MESSAGE_ID" | grep -Eq '^[0-9]+$'; then
    echo "Error: messageid must be an integer (got '$MESSAGE_ID')."
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Error: the ${CONTAINER} container is not running."
    echo "Run ./scripts/setup-database.sh first."
    exit 1
fi

echo "Deleting message $MESSAGE_ID"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB" -c \
    "DELETE FROM message WHERE messageid=$MESSAGE_ID RETURNING messageid, \"from\", message;"
