-- ============================================
-- Migration Mollie vers PayPal
-- Date: 2026-01-08
-- ============================================

-- 1. Ajouter la colonne paypal_order_id
ALTER TABLE orders ADD COLUMN paypal_order_id VARCHAR(50) NULL;
CREATE INDEX ix_orders_paypal_order_id ON orders(paypal_order_id);

-- 2. Mettre à jour le provider dans webhook_events
-- Les anciens webhooks Mollie restent avec provider='mollie'
-- Les nouveaux auront provider='paypal'

-- ============================================
-- CLEANUP (À exécuter APRÈS validation complète en production)
-- ============================================

-- 3. Optionnel: Après migration complète, supprimer mollie_payment_id
-- ⚠️ NE PAS EXÉCUTER avant d'avoir vérifié que toutes les anciennes commandes sont traitées
-- ALTER TABLE orders DROP COLUMN mollie_payment_id;

-- 4. Optionnel: Nettoyer les anciens webhooks Mollie (après 90 jours)
-- DELETE FROM webhook_events WHERE provider = 'mollie' AND created_at < DATE_SUB(NOW(), INTERVAL 90 DAY);

