#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour nettoyer les données de test de la base de données.

Usage: python cleanup.py

ATTENTION: Ce script supprime TOUTES les commandes, tickets, scans et webhook events.
À utiliser uniquement pour nettoyer les données de test.
"""

import sys
import io
import os
from datetime import datetime
from typing import Dict

from app.core.config import settings
from app.db.database import SessionLocal
from app.db import models


# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def print_header(title: str):
    """Affiche un header formaté"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_data() -> Dict[str, int]:
    """
    Compte les enregistrements dans chaque table concernée.

    Returns:
        Dict avec le nombre d'enregistrements par table
    """
    db = SessionLocal()
    try:
        counts = {
            "orders": db.query(models.Order).count(),
            "order_items": db.query(models.OrderItem).count(),
            "tickets": db.query(models.Ticket).count(),
            "scan_logs": db.query(models.ScanLog).count(),
            "webhook_events": db.query(models.WebhookEvent).count(),
        }

        # Compter les event_packs avec sold_count > 0
        counts["event_packs_with_sales"] = db.query(models.EventPack).filter(
            models.EventPack.sold_count > 0
        ).count()

        return counts
    finally:
        db.close()


def count_pdf_files() -> int:
    """Compte les fichiers PDF dans temp_pdfs/"""
    pdf_dir = "temp_pdfs"
    if not os.path.exists(pdf_dir):
        return 0

    try:
        files = [f for f in os.listdir(pdf_dir) if f.endswith('.pdf')]
        return len(files)
    except Exception:
        return 0


def print_data_summary(counts: Dict[str, int]):
    """Affiche un résumé des données présentes"""
    print("\n📊 ÉTAT ACTUEL DE LA BASE DE DONNÉES")
    print("-" * 60)
    print(f"  Commandes (orders):           {counts['orders']:>6}")
    print(f"  Articles (order_items):       {counts['order_items']:>6}")
    print(f"  Tickets:                      {counts['tickets']:>6}")
    print(f"  Scans (scan_logs):            {counts['scan_logs']:>6}")
    print(f"  Webhooks (webhook_events):    {counts['webhook_events']:>6}")
    print(f"  Packs vendus (sold_count>0):  {counts['event_packs_with_sales']:>6}")

    pdf_count = count_pdf_files()
    print(f"  Fichiers PDF (temp_pdfs/):    {pdf_count:>6}")

    print("-" * 60)

    total = sum([
        counts['orders'],
        counts['order_items'],
        counts['tickets'],
        counts['scan_logs'],
        counts['webhook_events']
    ])
    print(f"  TOTAL enregistrements:        {total:>6}")
    print()


def dry_run_cleanup():
    """
    Mode dry-run: affiche ce qui sera supprimé sans le faire.
    """
    print_header("MODE DRY-RUN - APERÇU")

    counts = check_data()

    if all(count == 0 for count in counts.values()) and count_pdf_files() == 0:
        print("\n✅ Aucune donnée à nettoyer - La base est déjà vide!")
        return

    print_data_summary(counts)

    print("🗑️  CE QUI SERA SUPPRIMÉ:")
    print("-" * 60)

    if counts['scan_logs'] > 0:
        print(f"  ✓ {counts['scan_logs']} scan logs")

    if counts['webhook_events'] > 0:
        print(f"  ✓ {counts['webhook_events']} webhook events")

    if counts['orders'] > 0:
        print(f"  ✓ {counts['orders']} commandes")
        print(f"    → Suppression automatique de {counts['order_items']} order items (cascade)")
        print(f"    → Suppression automatique de {counts['tickets']} tickets (cascade)")

    if counts['event_packs_with_sales'] > 0:
        print(f"  ✓ Réinitialisation de sold_count pour {counts['event_packs_with_sales']} packs")

    pdf_count = count_pdf_files()
    if pdf_count > 0:
        print(f"  ✓ {pdf_count} fichiers PDF dans temp_pdfs/")

    print("-" * 60)
    print("\n💡 Aucune donnée n'a été supprimée (mode dry-run)")


def reset_sold_counts():
    """
    Réinitialise le sold_count de tous les event_packs à 0.
    """
    db = SessionLocal()
    try:
        updated = db.query(models.EventPack).filter(
            models.EventPack.sold_count > 0
        ).update({"sold_count": 0}, synchronize_session=False)

        db.commit()

        if updated > 0:
            print(f"  ✓ sold_count réinitialisé pour {updated} pack(s)")

        return updated
    except Exception as e:
        db.rollback()
        print(f"  ✗ Erreur réinitialisation sold_count: {e}")
        return 0
    finally:
        db.close()


def cleanup_pdf_files() -> int:
    """
    Supprime tous les fichiers PDF dans temp_pdfs/.

    Returns:
        Nombre de fichiers supprimés
    """
    pdf_dir = "temp_pdfs"
    if not os.path.exists(pdf_dir):
        return 0

    deleted = 0
    try:
        for filename in os.listdir(pdf_dir):
            if filename.endswith('.pdf'):
                file_path = os.path.join(pdf_dir, filename)
                try:
                    os.remove(file_path)
                    deleted += 1
                except Exception as e:
                    print(f"  ⚠️  Erreur suppression {filename}: {e}")
    except Exception as e:
        print(f"  ✗ Erreur accès temp_pdfs/: {e}")

    return deleted


def cleanup_all():
    """
    Supprime toutes les données de test de la base de données.

    Ordre de suppression:
    1. ScanLogs (indépendants)
    2. WebhookEvents (indépendants)
    3. Orders (cascade automatique vers OrderItems et Tickets)
    4. Réinitialisation sold_count dans EventPacks
    5. Suppression fichiers PDF
    """
    print_header("NETTOYAGE DES DONNÉES DE TEST")

    # Vérifier les données avant suppression
    counts_before = check_data()

    if all(count == 0 for count in counts_before.values()) and count_pdf_files() == 0:
        print("\n✅ Aucune donnée à nettoyer - La base est déjà vide!")
        return

    print_data_summary(counts_before)

    # Confirmation finale
    print("⚠️  ATTENTION: Cette opération est IRRÉVERSIBLE!")
    print("⚠️  Toutes les commandes, tickets et scans seront supprimés définitivement.")
    confirm = input("\n👉 Tapez 'OUI' en majuscules pour confirmer: ").strip()

    if confirm != "OUI":
        print("\n❌ Opération annulée - Aucune donnée supprimée")
        return

    print("\n🗑️  SUPPRESSION EN COURS...")
    print("-" * 60)

    db = SessionLocal()
    results = {
        "scan_logs": 0,
        "webhook_events": 0,
        "orders": 0,
        "order_items": 0,
        "tickets": 0,
        "event_packs_reset": 0,
        "pdf_files": 0,
        "errors": []
    }

    try:
        # 1. Supprimer les ScanLogs
        try:
            scan_logs = db.query(models.ScanLog).all()
            results["scan_logs"] = len(scan_logs)
            for log in scan_logs:
                db.delete(log)
            db.commit()
            print(f"  ✓ {results['scan_logs']} scan logs supprimés")
        except Exception as e:
            db.rollback()
            results["errors"].append(f"ScanLogs: {e}")
            print(f"  ✗ Erreur suppression scan_logs: {e}")

        # 2. Supprimer les WebhookEvents
        try:
            webhook_events = db.query(models.WebhookEvent).all()
            results["webhook_events"] = len(webhook_events)
            for event in webhook_events:
                db.delete(event)
            db.commit()
            print(f"  ✓ {results['webhook_events']} webhook events supprimés")
        except Exception as e:
            db.rollback()
            results["errors"].append(f"WebhookEvents: {e}")
            print(f"  ✗ Erreur suppression webhook_events: {e}")

        # 3. Compter les OrderItems et Tickets avant suppression (pour le rapport)
        results["order_items"] = db.query(models.OrderItem).count()
        results["tickets"] = db.query(models.Ticket).count()

        # 4. Supprimer les Orders (cascade automatique vers OrderItems et Tickets)
        try:
            orders = db.query(models.Order).all()
            results["orders"] = len(orders)
            for order in orders:
                db.delete(order)
            db.commit()
            print(f"  ✓ {results['orders']} commandes supprimées")
            print(f"    → {results['order_items']} order items supprimés (cascade)")
            print(f"    → {results['tickets']} tickets supprimés (cascade)")
        except Exception as e:
            db.rollback()
            results["errors"].append(f"Orders: {e}")
            print(f"  ✗ Erreur suppression orders: {e}")

    finally:
        db.close()

    # 5. Réinitialiser les sold_count
    try:
        results["event_packs_reset"] = reset_sold_counts()
    except Exception as e:
        results["errors"].append(f"EventPacks reset: {e}")

    # 6. Supprimer les fichiers PDF
    try:
        results["pdf_files"] = cleanup_pdf_files()
        if results["pdf_files"] > 0:
            print(f"  ✓ {results['pdf_files']} fichiers PDF supprimés")
    except Exception as e:
        results["errors"].append(f"PDF files: {e}")
        print(f"  ✗ Erreur suppression PDF: {e}")

    # Rapport final
    print("-" * 60)

    if results["errors"]:
        print(f"\n⚠️  NETTOYAGE TERMINÉ AVEC {len(results['errors'])} ERREUR(S)")
        for error in results["errors"]:
            print(f"  ❌ {error}")
    else:
        print("\n✅ NETTOYAGE TERMINÉ AVEC SUCCÈS")

    # Vérification post-nettoyage
    counts_after = check_data()
    pdf_after = count_pdf_files()

    print("\n📊 ÉTAT APRÈS NETTOYAGE")
    print("-" * 60)
    print(f"  Commandes restantes:     {counts_after['orders']}")
    print(f"  Tickets restants:        {counts_after['tickets']}")
    print(f"  Scans restants:          {counts_after['scan_logs']}")
    print(f"  Webhooks restants:       {counts_after['webhook_events']}")
    print(f"  PDF restants:            {pdf_after}")
    print("-" * 60)

    total_deleted = (
        results["scan_logs"] +
        results["webhook_events"] +
        results["orders"] +
        results["order_items"] +
        results["tickets"]
    )
    print(f"\n🗑️  Total supprimé: {total_deleted} enregistrements + {results['pdf_files']} fichiers")


def main():
    """Point d'entrée principal du script"""
    print_header("NETTOYAGE DES DONNÉES DE TEST")
    print(f"\nEnvironnement: {settings.environment}")
    print(f"Base de données: {settings.mysql_host}")

    # Avertissement si en production
    if settings.is_production:
        print("\n⚠️  ATTENTION: Vous êtes en mode PRODUCTION!")
        print("⚠️  Ce script va supprimer TOUTES les données de test.")
        confirm_prod = input("\n👉 Tapez 'PRODUCTION' pour continuer: ").strip()
        if confirm_prod != "PRODUCTION":
            print("\n❌ Opération annulée")
            return 1

    print("\n📋 Options disponibles:")
    print("  1. Voir l'aperçu (dry-run) - Aucune suppression")
    print("  2. Nettoyer TOUTES les données de test")
    print("  0. Annuler")

    choice = input("\n👉 Votre choix: ").strip()

    try:
        if choice == "1":
            dry_run_cleanup()
            print("\n💡 Pour effectuer le nettoyage réel, relancez avec l'option 2")
        elif choice == "2":
            cleanup_all()
        elif choice == "0":
            print("\n👋 Opération annulée")
        else:
            print("\n❌ Option invalide")
            return 1

        print()
        return 0

    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
