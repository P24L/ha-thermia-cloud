#!/usr/bin/env bash
# Copy the integration to a Home Assistant box over SSH (no rsync needed).
# Stops before the restart unless --restart is given. Nothing is hard-coded: pass your own values.
#
#   HA_HOST=root@<ha-host> HA_KEY=~/.ssh/<your_key> scripts/deploy_dev.sh [--restart] [--yes] [--dry-run]
#
# Take a Home Assistant backup first (the script asks, unless --yes).
set -euo pipefail

: "${HA_HOST:?set HA_HOST, e.g. root@<ha-host>}"
HA_KEY="${HA_KEY:-}"
RESTART=0 YES=0 DRY=0
for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=1 ;;
    --yes) YES=1 ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

SRC="$(cd "$(dirname "$0")/.." && pwd)/custom_components/thermia_cloud"
VERSION="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$SRC/manifest.json")"
SSH=(ssh)
[ -n "$HA_KEY" ] && SSH+=(-i "$HA_KEY")
run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }

echo "Deploying thermia_cloud $VERSION to $HA_HOST:/config/custom_components/"
if [ "$YES" != 1 ] && [ "$DRY" != 1 ]; then
  read -r -p "Is a fresh Home Assistant backup in place? [y/N] " ok
  [ "$ok" = "y" ] || { echo "Aborted."; exit 1; }
fi

# upload into a temporary folder, then swap, so a failed copy never leaves a half-installed integration
TMP="/tmp/thermia_cloud_new"
if [ "$DRY" = 1 ]; then
  echo "[dry-run] tar (no __pycache__) | ${SSH[*]} $HA_HOST 'rm -rf $TMP && mkdir -p $TMP && tar -C $TMP -xf -'"
else
  COPYFILE_DISABLE=1 tar -C "$(dirname "$SRC")" --exclude='__pycache__' -cf - thermia_cloud \
    | "${SSH[@]}" "$HA_HOST" "rm -rf $TMP && mkdir -p $TMP && tar -C $TMP -xf -"
fi
run "${SSH[@]}" "$HA_HOST" "rm -rf /config/custom_components/thermia_cloud && mkdir -p /config/custom_components && mv $TMP/thermia_cloud /config/custom_components/thermia_cloud && rm -rf $TMP"
run "${SSH[@]}" "$HA_HOST" "ha core check"

if [ "$RESTART" = 1 ]; then
  run "${SSH[@]}" "$HA_HOST" "ha core restart"
else
  echo "Copied and checked. Restart Home Assistant yourself (or rerun with --restart) when it is safe."
fi
