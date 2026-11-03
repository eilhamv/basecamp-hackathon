# Source this in EVERY terminal, from inside build/:   source env.sh
# Activates the venv (build/.venv or the repo's .venv), loads the key from .env (repo root or build/),
# and removes any gateway URL so Managed Agents calls go to the Claude API. Never prints the key.
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; elif [ -f ../.venv/bin/activate ]; then source ../.venv/bin/activate; fi
set -a; for f in ../.env .env; do [ -f "$f" ] && source "$f"; done; set +a
unset ANTHROPIC_BASE_URL
if [ -n "$ANTHROPIC_API_KEY" ]; then echo "workspace key loaded"; else echo "no key: add ANTHROPIC_API_KEY to .env (see README)"; fi
