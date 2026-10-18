#!/usr/bin/env bash
set -euo pipefail
rm -rf "$HOME/.local/share/screapers"
rm -f "$HOME/.local/bin/screapers" \
      "$HOME/.local/share/applications/screapers.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/screapers.svg"
echo "Screapers desinstalado (app, lanzador, icono y datasets eliminados). Si también quieres borrar tu configuración, elimina ~/.config/screapers manualmente."
