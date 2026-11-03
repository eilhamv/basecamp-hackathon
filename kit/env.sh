# Source this in EVERY terminal, from inside build/:   source env.sh
# Loads the venv and the workspace key from .env (git-ignored), and removes any gateway URL
# so Managed Agents calls go to the workspace API. Never prints the key.
source .venv/bin/activate
set -a; [ -f .env ] && source .env; set +a
unset ANTHROPIC_BASE_URL
if [ -n "$ANTHROPIC_API_KEY" ]; then echo "workspace key loaded"; else echo "no key: create .env here in build/ (README step 3)"; fi
