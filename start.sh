#!/bin/bash
# Script de démarrage avec configuration des libs pour WeasyPrint

# Configuration des chemins pour les bibliothèques Nix
export LD_LIBRARY_PATH="/root/.nix-profile/lib:/nix/var/nix/profiles/default/lib:$LD_LIBRARY_PATH"
export GI_TYPELIB_PATH="/root/.nix-profile/lib/girepository-1.0:/nix/var/nix/profiles/default/lib/girepository-1.0"
export FONTCONFIG_PATH="/root/.nix-profile/etc/fonts:/nix/var/nix/profiles/default/etc/fonts"

# Lancer uvicorn
exec /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2

