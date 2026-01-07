-- Migration: Rendre pack_id et quantity nullable pour supporter le système de panier
-- Date: 2025-12-23
-- Raison: Les commandes de type panier (multi-pack) n'ont pas de pack_id unique
--         Ces colonnes sont legacy et remplacées par OrderItems

-- 1. Rendre pack_id nullable (pour commandes panier)
ALTER TABLE orders
MODIFY COLUMN pack_id VARCHAR(36) NULL
COMMENT 'Pack unique (legacy) - NULL pour commandes panier multi-pack';

-- 2. Rendre quantity nullable (pour commandes panier)
ALTER TABLE orders
MODIFY COLUMN quantity INT NULL
COMMENT 'Quantité (legacy) - NULL pour commandes panier, calculé via OrderItems';

-- Vérification
SELECT
    COLUMN_NAME,
    IS_NULLABLE,
    COLUMN_TYPE,
    COLUMN_COMMENT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'orders'
  AND COLUMN_NAME IN ('pack_id', 'quantity');
