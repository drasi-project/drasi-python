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
# building hierarchy (1 Building, 3 Floors, 9 Rooms).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABASE_DIR="$SCRIPT_DIR/../database"

echo "=== Building Comfort - Database Setup ==="
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
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if docker exec building-comfort-postgres pg_isready -U postgres -d building_comfort &> /dev/null; then
        echo "PostgreSQL is ready!"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "  Waiting... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Error: PostgreSQL failed to start within the timeout"
    echo "Check logs with: docker logs building-comfort-postgres"
    exit 1
fi

# Apply the schema and seed data over stdin. We pipe init.sql into psql with
# `docker exec -i` instead of bind-mounting it into the container. A bind mount
# would break under docker-outside-of-docker (the dev container's file path does
# not exist on the host's Docker daemon); piping over stdin works the same way
# for the dev container, Codespaces, and bare-metal runs.
echo "Applying schema and seed data..."
docker exec -i building-comfort-postgres \
    psql -v ON_ERROR_STOP=1 -U postgres -d building_comfort < "$DATABASE_DIR/init.sql"

echo
echo "Verifying database setup..."

PUB_EXISTS=$(docker exec building-comfort-postgres psql -U drasi_user -d building_comfort -tAc \
    "SELECT 1 FROM pg_publication WHERE pubname = 'drasi_building_comfort_pub';" 2>/dev/null || echo "0")
if [ "$PUB_EXISTS" = "1" ]; then
    echo "  Publication: drasi_building_comfort_pub [OK]"
else
    echo "  Publication: drasi_building_comfort_pub [MISSING]"
fi

SLOT_EXISTS=$(docker exec building-comfort-postgres psql -U drasi_user -d building_comfort -tAc \
    "SELECT 1 FROM pg_replication_slots WHERE slot_name = 'drasi_building_comfort_slot';" 2>/dev/null || echo "0")
if [ "$SLOT_EXISTS" = "1" ]; then
    echo "  Replication slot: drasi_building_comfort_slot [OK]"
else
    echo "  Replication slot: drasi_building_comfort_slot [MISSING]"
fi

echo
echo "Seeded rooms:"
docker exec building-comfort-postgres psql -U drasi_user -d building_comfort -c \
    "SELECT id, name, temperature, humidity, co2, floor_id FROM \"Room\" ORDER BY id;"

echo
echo "=== Database setup complete! ==="
echo
echo "Connection details:"
echo "  Host: localhost"
echo "  Port: ${POSTGRES_HOST_PORT:-5732}"
echo "  Database: building_comfort"
echo "  User: drasi_user"
echo "  Password: drasi_password"
