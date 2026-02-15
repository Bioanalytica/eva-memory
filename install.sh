#!/usr/bin/env bash
# Eva Memory - Install Script
# Checks prerequisites, installs dependencies, and prints setup instructions.
#
# Usage:
#   ./install.sh            # install
#   ./install.sh --verify   # post-install health check
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()   { echo -e "${RED}[error]${NC} $*"; }

# --------------------------------------------------------------------------
# Verify mode
# --------------------------------------------------------------------------
if [[ "${1:-}" == "--verify" ]]; then
  echo ""
  info "Running post-install health checks..."
  echo ""

  PASS=0
  FAIL=0

  check() {
    if eval "$2" &>/dev/null; then
      ok "$1"
      ((PASS++))
    else
      err "$1"
      ((FAIL++))
    fi
  }

  check "bun installed"              "command -v bun"
  check "uv installed"               "command -v uv"
  check "node_modules exist"         "[ -d '$DIR/mcp-server/node_modules' ]"
  check "memory.py accessible"       "[ -f '$DIR/scripts/memory.py' ]"
  check "init.cypher accessible"     "[ -f '$DIR/schema/init.cypher' ]"

  # Check Neo4j connectivity (if env vars set)
  if [[ -n "${EVA_NEO4J_PASS:-}" ]]; then
    check "Neo4j reachable" "uv run --script '$DIR/scripts/init_schema.py' 2>&1 | grep -q 'Connected'"
  else
    warn "EVA_NEO4J_PASS not set — skipping Neo4j check"
  fi

  # Check Docker services
  if command -v docker &>/dev/null; then
    check "eva-neo4j container running"  "docker ps --format '{{.Names}}' | grep -q eva-neo4j"
    check "eva-chroma container running" "docker ps --format '{{.Names}}' | grep -q eva-chroma"
  else
    warn "docker not found — skipping container checks"
  fi

  echo ""
  info "Results: ${PASS} passed, ${FAIL} failed"
  [[ $FAIL -eq 0 ]] && ok "All checks passed!" || err "Some checks failed."
  exit $FAIL
fi

# --------------------------------------------------------------------------
# Install mode
# --------------------------------------------------------------------------
echo ""
echo "  Eva Memory — Install"
echo "  ====================="
echo ""

# Check prerequisites
MISSING=0

if command -v bun &>/dev/null; then
  ok "bun $(bun --version)"
else
  err "bun not found — install from https://bun.sh"
  ((MISSING++))
fi

if command -v uv &>/dev/null; then
  ok "uv $(uv --version 2>&1 | head -1)"
else
  err "uv not found — install from https://docs.astral.sh/uv/"
  ((MISSING++))
fi

if [[ $MISSING -gt 0 ]]; then
  echo ""
  err "Missing $MISSING prerequisite(s). Install them and re-run."
  exit 1
fi

# Install MCP server dependencies
echo ""
info "Installing MCP server dependencies..."
cd "$DIR/mcp-server"
bun install
ok "MCP server dependencies installed"

# Initialize Neo4j schema (if password is set)
echo ""
if [[ -n "${EVA_NEO4J_PASS:-}" ]]; then
  info "Initializing Neo4j schema..."
  cd "$DIR"
  EVA_NEO4J_URI="${EVA_NEO4J_URI:-bolt://localhost:7687}" uv run scripts/init_schema.py
  ok "Neo4j schema initialized"
else
  warn "EVA_NEO4J_PASS not set — skipping schema initialization"
  info "Set it and run: EVA_NEO4J_PASS=yourpass uv run scripts/init_schema.py"
fi

# Print registration instructions
echo ""
echo "  ====================="
echo "  Next Steps"
echo "  ====================="
echo ""
info "1. Register the MCP server with Claude Code:"
echo ""
echo "  claude mcp add eva-memory \\"
echo "    --scope user \\"
echo "    -e EVA_MEMORY_DIR=$DIR \\"
echo "    -e EVA_NEO4J_URI=bolt://localhost:7687 \\"
echo "    -e EVA_NEO4J_PASS=YOUR_PASSWORD \\"
echo "    -e EVA_STORE_PATH=$HOME/.eva-memory \\"
echo "    -- bun run $DIR/mcp-server/src/index.ts"
echo ""
info "2. Merge hooks into ~/.claude/settings.json:"
echo ""
echo "  See config/settings-hooks.json for the hook definitions."
echo "  Copy the 'hooks' and 'env' blocks into your existing settings.json."
echo "  Replace \$EVA_MEMORY_DIR with: $DIR"
echo ""
info "3. Start a new Claude Code session to verify hooks fire."
echo ""
info "Run './install.sh --verify' to check everything is working."
echo ""
