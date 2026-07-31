#!/bin/bash
# Post-create script for the Getting Started tutorial (Python).

set -e

echo "🔧 Initializing the Getting Started (Python) tutorial environment..."

# Resolve the tutorial directory from this script's location so the script works
# regardless of the current working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TUTORIAL_DIR="$REPO_ROOT/tutorials/getting-started"

# Install the tutorial's Python dependency (drasi-lib). The devcontainer's Python
# feature provides a pip that is not externally managed, so a plain install works.
echo "🐍 Installing Python dependencies..."
cd "$TUTORIAL_DIR"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo ""
echo "✅ Getting Started (Python) tutorial environment is ready!"
echo "   Next: run 'bash scripts/start-demo.sh' (you are already in tutorials/getting-started)"
