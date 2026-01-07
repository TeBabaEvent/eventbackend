#!/bin/bash
# Script de démarrage avec configuration des libs pour WeasyPrint

# Configuration des chemins pour les bibliothèques Nix
export LD_LIBRARY_PATH="/root/.nix-profile/lib:/nix/var/nix/profiles/default/lib:/usr/lib:/lib:$LD_LIBRARY_PATH"
export LIBRARY_PATH="/root/.nix-profile/lib:/nix/var/nix/profiles/default/lib"
export GI_TYPELIB_PATH="/root/.nix-profile/lib/girepository-1.0:/nix/var/nix/profiles/default/lib/girepository-1.0"
export FONTCONFIG_PATH="/root/.nix-profile/etc/fonts:/nix/var/nix/profiles/default/etc/fonts"
export XDG_DATA_DIRS="/root/.nix-profile/share:/nix/var/nix/profiles/default/share:$XDG_DATA_DIRS"

# Debug: afficher les libs disponibles
echo "Checking for libgobject..."
ls -la /root/.nix-profile/lib/libgobject* 2>/dev/null || echo "Not in /root/.nix-profile/lib"
ls -la /nix/var/nix/profiles/default/lib/libgobject* 2>/dev/null || echo "Not in /nix/var/nix/profiles/default/lib"

# Lancer uvicorn
exec /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2

