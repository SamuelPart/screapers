#!/usr/bin/env bash
# Construye screapers_<versión>_all.deb (Ubuntu/Debian). Uso: ./packaging/build-deb.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(python3 -c "from screapers import __version__; print(__version__)")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/share/screapers" "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps"
cp -r screapers "$STAGE/usr/share/screapers/"
find "$STAGE/usr/share/screapers" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
printf '#!/bin/sh\nPYTHONPATH=/usr/share/screapers exec python3 -m screapers "$@"\n' > "$STAGE/usr/bin/screapers"
chmod 755 "$STAGE/usr/bin/screapers"
sed 's|^Exec=.*|Exec=/usr/bin/screapers|' packaging/screapers.desktop > "$STAGE/usr/share/applications/screapers.desktop"
cp packaging/screapers.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/screapers.svg"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: screapers
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-tk
Maintainer: SamuelPart
Description: Scraping web con interfaz de escritorio, bots de IA y seguridad
 Extrae datos de sitios web desde una ventana (sin terminal), con ritmo
 educado anti-bloqueo, respeto de robots.txt, mascara de datos personales
 y auditoria local verificable.
EOF
OUT="screapers_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
echo "✅ Creado $OUT  —  instala con:  sudo apt install ./$OUT"
