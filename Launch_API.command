#!/bin/bash
#
# Lanceur macOS "un clic" pour l'application BOAMP.
# Rôle: créer/activer un venv, installer les dépendances si nécessaire,
# démarrer le serveur Flask et ouvrir le navigateur.
#
# One-click launcher for macOS (double-clickable .command)
# - Creates a virtualenv if missing
# - Installs dependencies
# - Starts the Flask server
# - Opens the browser to http://localhost:8000

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"  # Répertoire racine du projet
cd "$DIR"

# Detect python executable
PY=python3  # Binaire Python à utiliser (fallback sur `python`)
if ! command -v "$PY" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PY=python
  else
    echo "Python non trouvé. Installez Python 3 depuis https://www.python.org/downloads/" >&2
    read -r -p "Appuyez sur Entrée pour fermer…" _
    exit 1
  fi
fi

# Create venv if needed
if [ ! -d "$DIR/.venv" ]; then
  # Crée l'environnement virtuel s'il n'existe pas
  "$PY" -m venv "$DIR/.venv"
fi

# Activate venv
source "$DIR/.venv/bin/activate"  # Active le venv

# Install requirements only if needed (missing pkgs or changed lock)
REQ_FILE="$DIR/Back-end/requirements.txt"
STAMP_FILE="$DIR/.venv/.requirements.sha256"

calc_hash() {
  python - "$REQ_FILE" <<'PY'
import hashlib, sys; p=sys.argv[1]; print(hashlib.sha256(open(p,'rb').read()).hexdigest())
PY
}

NEED_INSTALL=0
REQ_HASH=$(calc_hash)
CUR_HASH=""
if [ -f "$STAMP_FILE" ]; then CUR_HASH=$(cat "$STAMP_FILE" 2>/dev/null || echo ""); fi

# Check if required modules are present
CHK=$(python - <<'PY'
import importlib
mods=['flask','certifi']
ok=True
for m in mods:
    try: importlib.import_module(m)
    except Exception: ok=False
print('OK' if ok else 'MISS')
PY
)

if [ "$CHK" != "OK" ] || [ "$REQ_HASH" != "$CUR_HASH" ]; then
  NEED_INSTALL=1
fi

if [ "$NEED_INSTALL" = "1" ]; then
  # Met à jour pip et installe les dépendances si nécessaires
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -r "$REQ_FILE"
  echo "$REQ_HASH" > "$STAMP_FILE"
fi

# If a local CA is provided, export env var so the app trusts it
if [ -f "$DIR/Back-end/local_ca.pem" ]; then
  # Ajoute un CA local (entreprise) si fourni pour éviter les erreurs SSL
  export LOCAL_CA_FILE="$DIR/Back-end/local_ca.pem"
  export SSL_CERT_FILE="$DIR/Back-end/local_ca.pem"
fi

# Prefer Explore v2.1 by default for better date filtering
export PREFER_EXPLORE=${PREFER_EXPLORE:-1}  # Explore v2.1 prioritaire

# Open browser shortly after server starts
(
  sleep 2  # Laisse le temps au serveur de démarrer
  open "http://localhost:8000"
) &

# Run server (Ctrl+C to stop)
python "$DIR/Back-end/app.py"  # Démarre le serveur Flask (Ctrl+C pour arrêter)

# Keep window open after server exits
echo
read -r -p "Serveur arrêté. Appuyez sur Entrée pour fermer…" _
