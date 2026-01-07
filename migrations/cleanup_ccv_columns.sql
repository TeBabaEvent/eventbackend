-- Nettoyage des colonnes CCV (Option 1: Nettoyage Complet)
-- Date: 2025-12-23
-- Description: Supprime les colonnes CCV legacy de la table orders

-- ⚠️ ATTENTION: Ne pas exécuter si vous avez des données CCV en production!
-- Ce script est prévu pour une base de données vide ou après migration complète

-- ============================================
-- 1. Vérifier qu'il n'y a pas de données CCV
-- ============================================

-- Vérifier les commandes avec références CCV
SELECT COUNT(*) as commandes_avec_ccv
FROM orders
WHERE ccv_reference IS NOT NULL;

-- Si le résultat est > 0, NE PAS CONTINUER sans sauvegarder les données!

-- ============================================
-- 2. Supprimer les colonnes CCV
-- ============================================

-- Supprimer la colonne ccv_reference
ALTER TABLE orders DROP COLUMN ccv_reference;

-- Supprimer la colonne ccv_failure_code
ALTER TABLE orders DROP COLUMN ccv_failure_code;

-- ============================================
-- 3. Vérifications post-nettoyage
-- ============================================

-- Vérifier la structure de la table
DESCRIBE orders;

-- Vérifier que mollie_payment_id existe
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'orders'
AND TABLE_SCHEMA = 'railway'
AND COLUMN_NAME = 'mollie_payment_id';

-- Résultat attendu:
-- mollie_payment_id | varchar(50) | YES

-- ============================================
-- 4. Statistiques
-- ============================================

-- Compter les commandes totales
SELECT COUNT(*) as total_commandes FROM orders;

-- Compter les commandes avec Mollie
SELECT COUNT(*) as commandes_mollie
FROM orders
WHERE mollie_payment_id IS NOT NULL;

-- ============================================
-- ✅ Nettoyage terminé!
-- ============================================

-- Les colonnes CCV ont été supprimées.
-- La base de données utilise maintenant 100% Mollie.
