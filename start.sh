#!/bin/bash
# Script de démarrage avec configuration des libs pour WeasyPrint

# Trouver dynamiquement les chemins Nix (chercher uniquement dans /lib/)
NIX_GLIB_PATH=$(find /nix/store -path "*/lib/libgobject-2.0.so*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
NIX_PANGO_PATH=$(find /nix/store -path "*/lib/libpango-1.0.so*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
NIX_CAIRO_PATH=$(find /nix/store -path "*/lib/libcairo.so*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
NIX_GDK_PATH=$(find /nix/store -path "*/lib/libgdk_pixbuf-2.0.so*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
NIX_FONTCONFIG_PATH=$(find /nix/store -path "*/lib/libfontconfig.so*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
NIX_HARFBUZZ_PATH=$(find /nix/store -path "*/lib/libharfbuzz.so*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
NIX_FRIBIDI_PATH=$(find /nix/store -path "*/lib/libfribidi.so*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)

echo "Found library paths:"
echo "  GLIB: $NIX_GLIB_PATH"
echo "  PANGO: $NIX_PANGO_PATH"
echo "  CAIRO: $NIX_CAIRO_PATH"
echo "  GDK: $NIX_GDK_PATH"
echo "  FONTCONFIG: $NIX_FONTCONFIG_PATH"
echo "  HARFBUZZ: $NIX_HARFBUZZ_PATH"
echo "  FRIBIDI: $NIX_FRIBIDI_PATH"

# Construire LD_LIBRARY_PATH dynamiquement
export LD_LIBRARY_PATH="$NIX_GLIB_PATH:$NIX_PANGO_PATH:$NIX_CAIRO_PATH:$NIX_GDK_PATH:$NIX_FONTCONFIG_PATH:$NIX_HARFBUZZ_PATH:$NIX_FRIBIDI_PATH:/root/.nix-profile/lib:/nix/var/nix/profiles/default/lib:$LD_LIBRARY_PATH"

# GI_TYPELIB_PATH pour GObject introspection
NIX_GI_PATH=$(find /nix/store -path "*/lib/girepository-1.0" -type d 2>/dev/null | head -1)
if [ -n "$NIX_GI_PATH" ]; then
    export GI_TYPELIB_PATH="$NIX_GI_PATH:$GI_TYPELIB_PATH"
    echo "  GI_TYPELIB: $NIX_GI_PATH"
fi

# Fontconfig
NIX_FONTS_CONF=$(find /nix/store -name "fonts.conf" -path "*/etc/fonts/*" -type f 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
if [ -n "$NIX_FONTS_CONF" ]; then
    export FONTCONFIG_PATH="$NIX_FONTS_CONF"
    echo "  FONTCONFIG_PATH: $NIX_FONTS_CONF"
fi

echo "LD_LIBRARY_PATH set to: ${LD_LIBRARY_PATH:0:200}..."

# Vérifier que libgobject est trouvable
if [ -f "$NIX_GLIB_PATH/libgobject-2.0.so" ] || [ -f "$NIX_GLIB_PATH/libgobject-2.0.so.0" ]; then
    echo "✅ libgobject-2.0 found in $NIX_GLIB_PATH"
else
    echo "❌ WARNING: libgobject-2.0 NOT found in $NIX_GLIB_PATH"
    ls -la "$NIX_GLIB_PATH"/libgobject* 2>/dev/null || echo "No libgobject files found"
fi

# Lancer uvicorn
exec /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2
