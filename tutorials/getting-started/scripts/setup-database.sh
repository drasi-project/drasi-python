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

# Setup Database Script
# Starts PostgreSQL with logical replication (WAL) enabled for CDC and seeds the
# message feed.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABASE_DIR="$SCRIPT_DIR/../database"

echo "=== Getting Started - Database Setup ==="
echo

if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    echo "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "Error: Docker daemon is not running"
    echo "Please start Docker and try again"
    exit 1
fi

if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    echo "Error: docker-compose is not installed"
    echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "Using: $COMPOSE_CMD"
echo

echo "Stopping any existing PostgreSQL container..."
cd "$DATABASE_DIR"
$COMPOSE_CMD down -v 2>/dev/null || true

echo "Starting PostgreSQL with WAL replication..."
$COMPOSE_CMD up -d

echo "Waiting for PostgreSQL to be ready..."
POSTGRES_READY=false
for i in $(seq 1 30); do
    if docker exec getting-started-postgres pg_isready -h localhost -U postgres -d getting_started &> /dev/null; then
        echo "PostgreSQL is ready!"
        POSTGRES_READY=true
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 2
done

if [ "$POSTGRES_READY" != "true" ]; then
    echo "Error: PostgreSQL did not become ready within the timeout."
    echo "Check logs with: docker logs getting-started-postgres"
    exit 1
fi

echo
echo "Applying schema and seed data..."
docker exec -i getting-started-postgres \
    psql -v ON_ERROR_STOP=1 -U postgres -d getting_started < "$DATABASE_DIR/init.sql"

echo
echo "Seeded messages:"
docker exec getting-started-postgres psql -U drasi_user -d getting_started -c \
    "SELECT messageid, sender, message FROM message ORDER BY messageid;"

echo
echo "=== Database setup complete! ==="
echo "  PostgreSQL: localhost:${POSTGRES_HOST_PORT:-5752} / getting_started"
