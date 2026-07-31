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
# Starts PostgreSQL (orders, logical replication) and MySQL (vehicles, ROW-based
# binlog + GTID) and seeds both, so Drasi can stream their changes via CDC.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABASE_DIR="$SCRIPT_DIR/../database"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-root_admin}"

echo "=== Curbside Pickup - Database Setup ==="
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

echo "Stopping any existing containers..."
cd "$DATABASE_DIR"
$COMPOSE_CMD down -v 2>/dev/null || true

echo "Starting PostgreSQL and MySQL..."
$COMPOSE_CMD up -d

echo "Waiting for PostgreSQL to be ready..."
POSTGRES_READY=false
for i in $(seq 1 30); do
    if docker exec curbside-pickup-postgres pg_isready -h localhost -U postgres -d RetailOperations &> /dev/null; then
        echo "PostgreSQL is ready!"
        POSTGRES_READY=true
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 2
done

if [ "$POSTGRES_READY" != "true" ]; then
    echo "Error: PostgreSQL did not become ready within the timeout."
    echo "Check logs with: docker logs curbside-pickup-postgres"
    exit 1
fi

echo "Waiting for MySQL to be ready..."
MYSQL_READY=false
for i in $(seq 1 45); do
    if docker exec curbside-pickup-mysql mysqladmin ping -h localhost -uroot -p"$MYSQL_ROOT_PASSWORD" &> /dev/null; then
        echo "MySQL is ready!"
        MYSQL_READY=true
        break
    fi
    echo "  Waiting... ($i/45)"
    sleep 2
done

if [ "$MYSQL_READY" != "true" ]; then
    echo "Error: MySQL did not become ready within the timeout."
    echo "Check logs with: docker logs curbside-pickup-mysql"
    exit 1
fi

echo
echo "Seeding PostgreSQL (orders)..."
docker exec -i curbside-pickup-postgres \
    psql -v ON_ERROR_STOP=1 -U postgres -d RetailOperations < "$DATABASE_DIR/postgres-init.sql"

echo "Seeding MySQL (vehicles)..."
docker exec -i curbside-pickup-mysql \
    mysql -uroot -p"$MYSQL_ROOT_PASSWORD" < "$DATABASE_DIR/mysql-init.sql"

echo
echo "Seeded orders (PostgreSQL):"
docker exec curbside-pickup-postgres psql -U drasi_user -d RetailOperations -c \
    "SELECT id, customer_name, plate, status FROM orders ORDER BY id;"

echo "Seeded vehicles (MySQL):"
docker exec curbside-pickup-mysql \
    mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -D PhysicalOperations -e \
    "SELECT plate, make, model, color, location FROM vehicles ORDER BY plate;" 2>/dev/null

echo
echo "=== Database setup complete! ==="
echo "  PostgreSQL: localhost:${POSTGRES_HOST_PORT:-5742} / RetailOperations"
echo "  MySQL:      localhost:${MYSQL_HOST_PORT:-3309} / PhysicalOperations"
