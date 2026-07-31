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

# Start Demo Script
# Starts (and seeds) the database, then runs the console app in the foreground.
# The app embeds the Drasi engine and prints query changes. Leave it running in
# this terminal (Terminal 1); use a second terminal to add and delete messages
# with SQL (docker exec ... psql), as shown in the tutorial. Press Ctrl+C to
# stop, then run ./scripts/cleanup.sh.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUTORIAL_DIR="$SCRIPT_DIR/.."

bash "$SCRIPT_DIR/setup-database.sh"

echo
echo "Starting the console app (embeds the Drasi engine)..."
echo "On first run it downloads the Drasi plugins from ghcr.io — give it a moment."
echo

cd "$TUTORIAL_DIR"
exec python app.py
