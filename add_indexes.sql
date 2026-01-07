-- Migration: Ajout d'index pour optimisation des performances
-- Date: 2025-12-05
-- Description: Ajoute des index sur les colonnes fréquemment utilisées pour filtrage et tri

-- Index sur la table 'events'
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);

-- Index sur la table 'artists'
CREATE INDEX IF NOT EXISTS idx_artists_role ON artists(role);

-- Vérification des index créés
SHOW INDEX FROM events WHERE Key_name LIKE 'idx_events_%';
SHOW INDEX FROM artists WHERE Key_name = 'idx_artists_role';
