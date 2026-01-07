-- Migration CCV → Mollie
-- Date: 2025-12-23
-- Description: Ajoute la colonne mollie_payment_id à la table orders

-- ============================================
-- 1. Ajouter la colonne mollie_payment_id
-- ============================================

ALTER TABLE orders
ADD COLUMN mollie_payment_id VARCHAR(50) NULL COMMENT 'ID paiement Mollie (ex: tr_xxx)';

-- ============================================
-- 2. Créer un index pour mollie_payment_id
-- ============================================

CREATE INDEX idx_orders_mollie_payment_id ON orders(mollie_payment_id);

-- ============================================
-- 3. (Optionnel) Nettoyer les anciennes données CCV
-- ============================================

-- Si la base de données est vide, vous pouvez supprimer les colonnes CCV:
-- ALTER TABLE orders DROP COLUMN ccv_reference;
-- ALTER TABLE orders DROP COLUMN ccv_failure_code;

-- Sinon, les garder pour historique (recommandé)

-- ============================================
-- 4. Mettre à jour les webhooks pour Mollie
-- ============================================

-- Les webhooks avec provider='ccv' resteront dans l'historique
-- Les nouveaux webhooks utiliseront provider='mollie'

-- ============================================
-- Vérifications post-migration
-- ============================================

-- Vérifier que la colonne a été ajoutée:
-- DESCRIBE orders;

-- Vérifier l'index:
-- SHOW INDEXES FROM orders WHERE Column_name = 'mollie_payment_id';

-- Compter les commandes:
-- SELECT COUNT(*) FROM orders;

-- Vérifier qu'il n'y a pas de paiements en cours:
-- SELECT * FROM orders WHERE status = 'pending';
