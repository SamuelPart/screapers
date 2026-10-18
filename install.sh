#!/usr/bin/env bash
# Instala Screapers como app de escritorio para el usuario actual (Ubuntu/Debian y derivados).
# Sin root, salvo la dependencia del sistema python3-tk si falta.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Screapers: instalador para Linux"

# 1) Dependencias del sistema (interfaz gráfica Tk)
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo "==> Falta la interfaz gráfica (python3-tk). Intentando instalarla…"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y python3 python3-tk
  else
    echo "ERROR: instala python3 y python3-tk con el gestor de paquetes de tu distro." >&2
    exit 1
  fi
fi
python3 -c "import sys; assert sys.version_info >= (3,10), 'Se necesita Python 3.10+'"

# 2) Copia de la app a ~/.local/share/screapers
APP_DIR="$HOME/.local/share/screapers"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
rm -rf "$APP_DIR/screapers"
cp -r screapers "$APP_DIR/"
find "$APP_DIR/screapers" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
cp packaging/screapers.svg "$ICON_DIR/screapers.svg"

# 3) Lanzador + acceso directo en el menú de aplicaciones
cat > "$BIN_DIR/screapers" <<EOF
#!/bin/sh
PYTHONPATH="$APP_DIR" exec python3 -m screapers "\$@"
EOF
chmod +x "$BIN_DIR/screapers"

sed "s|^Exec=.*|Exec=$BIN_DIR/screapers|" packaging/screapers.desktop > "$DESKTOP_DIR/screapers.desktop"
chmod +x "$DESKTOP_DIR/screapers.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true

echo ""
echo "✅ Screapers instalado."
echo "   • Busca «Screapers» en el menú de aplicaciones de tu escritorio."
echo "   • O ejecútalo con:  ~/.local/bin/screapers"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "   (Añade $BIN_DIR a tu PATH si quieres lanzarlo como «screapers».)";; esac
echo "   • Desinstalar:  ./uninstall.sh"
