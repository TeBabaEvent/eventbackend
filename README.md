# Tebaba Backend API

Backend FastAPI pour l'application Tebaba avec authentification JWT et gestion d'événements.

## 📁 Structure du projet

```
backend/
├── app/                      # Code applicatif principal
│   ├── api/                  # Routes API
│   │   ├── deps.py          # Dépendances communes (auth, etc.)
│   │   └── v1/              # API version 1
│   │       ├── router.py    # Router principal
│   │       └── endpoints/   # Routes par ressource
│   │           ├── auth.py  # Authentification
│   │           ├── artists.py
│   │           ├── events.py
│   │           └── packs.py
│   ├── core/                # Configuration et sécurité
│   │   ├── config.py        # Configuration (settings)
│   │   └── security.py      # JWT, hashing, etc.
│   ├── db/                  # Base de données
│   │   ├── database.py      # Connexion et session
│   │   ├── models.py        # Modèles SQLAlchemy
│   │   └── migrations.py    # Migration automatique
│   ├── schemas/             # Schémas Pydantic
│   │   ├── auth.py
│   │   ├── artist.py
│   │   ├── event.py
│   │   └── pack.py
│   ├── utils/               # Utilitaires
│   │   └── serializers.py
│   └── main.py              # Point d'entrée FastAPI
├── run.py                   # Script de démarrage
├── requirements.txt
└── README.md
```

## 🚀 Installation

### 1. Créer un environnement virtuel

```bash
python -m venv venv
```

### 2. Activer l'environnement virtuel

```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

## ⚙️ Configuration

1. Créer un fichier `.env` à la racine du dossier `backend/` :

```env
# JWT Configuration
SECRET_KEY=your-secret-key-here-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# MySQL Database
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=babaevent

# Server
HOST=127.0.0.1
PORT=8000

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

2. Créer la base de données MySQL :

```sql
CREATE DATABASE babaevent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## 🎯 Lancement

### Démarrer le serveur

```bash
python run.py
```

**C'est tout !** 🎉

Au démarrage, l'application va automatiquement :
- ✅ Créer les tables si elles n'existent pas
- ✅ Ajouter les nouvelles colonnes si vous avez modifié un modèle
- ✅ Supprimer les colonnes obsolètes
- ✅ Ajouter les nouvelles tables
- ✅ Supprimer les tables obsolètes

L'API sera accessible sur : **http://127.0.0.1:8000**

## 🔄 Migration automatique

Le système de migration automatique détecte et applique automatiquement tous les changements de schéma au démarrage :

### Changements détectés automatiquement :
- ✅ **Nouvelles tables** → Créées automatiquement
- ✅ **Tables supprimées** → Supprimées automatiquement
- ✅ **Nouvelles colonnes** → Ajoutées automatiquement
- ✅ **Colonnes supprimées** → Supprimées automatiquement

### Exemple de modification :

1. **Ajouter un champ dans un modèle** :
```python
# Dans app/db/models.py
class Artist(Base):
    # ... champs existants ...
    phone = Column(String(20), nullable=True)  # Nouveau champ
```

2. **Redémarrer l'application** :
```bash
python run.py
```

3. **La migration s'applique automatiquement** :
```
🔄 MIGRATION AUTOMATIQUE DE LA BASE DE DONNÉES
============================================================

📝 Ajout de colonnes dans 'artists':
   + phone (VARCHAR(20))

✅ MIGRATION TERMINÉE
```

**Aucune commande manuelle nécessaire !** 🚀

## 📚 Documentation API

Documentation interactive disponible sur :
- **Swagger UI** : http://127.0.0.1:8000/docs
- **ReDoc** : http://127.0.0.1:8000/redoc

## 🔐 Authentification

### Connexion

```bash
POST /api/auth/login
Content-Type: application/json

{
    "email": "admin@example.com",
    "password": "your-password"
}
```

**Réponse** :
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "user": {
        "id": "uuid",
        "email": "admin@example.com",
        "username": "admin",
        "name": "Administrator",
        "role": "admin"
    }
}
```

### Utilisation du token

Ajoutez le header `Authorization: Bearer <token>` à vos requêtes protégées.

## 🛣️ Routes API

### Authentification
- `POST /api/auth/login` - Connexion
- `GET /api/auth/me` - Infos utilisateur connecté
- `POST /api/auth/logout` - Déconnexion

### Artistes
- `GET /api/artists` - Liste des artistes
- `GET /api/artists/{id}` - Détails d'un artiste
- `POST /api/artists` - Créer un artiste (admin)
- `PUT /api/artists/{id}` - Modifier un artiste (admin)
- `DELETE /api/artists/{id}` - Supprimer un artiste (admin)

### Événements
- `GET /api/events` - Liste des événements
- `GET /api/events/featured` - Événements à la une
- `GET /api/events/{id}` - Détails d'un événement
- `POST /api/events` - Créer un événement (admin)
- `PUT /api/events/{id}` - Modifier un événement (admin)
- `DELETE /api/events/{id}` - Supprimer un événement (admin)
- `PATCH /api/events/{event_id}/packs/{pack_id}/soldout` - Toggle soldout (admin)

### Packs
- `GET /api/packs` - Liste des packs
- `GET /api/packs/{id}` - Détails d'un pack
- `POST /api/packs` - Créer un pack (admin)
- `PUT /api/packs/{id}` - Modifier un pack (admin)
- `DELETE /api/packs/{id}` - Supprimer un pack (admin)

## 📝 Bonnes pratiques implémentées

✅ **Architecture modulaire** : Séparation claire des concerns (API, Core, DB, Schemas)  
✅ **API versionnée** : Structure `/api/v1` pour faciliter les évolutions  
✅ **Migration automatique** : Plus besoin de scripts de migration manuels  
✅ **Dépendances réutilisables** : Authentification et DB centralisées  
✅ **Sécurité** : JWT avec bcrypt pour le hashing  
✅ **Type safety** : Pydantic schemas pour validation  
✅ **Documentation** : Auto-générée avec Swagger/ReDoc  

## 🐛 Dépannage

### Erreur de connexion à la DB
Vérifiez que :
- MySQL est lancé
- Les credentials dans `.env` sont corrects
- La base de données existe

### Erreur de migration
Si la migration automatique échoue :
1. Vérifiez les logs au démarrage
2. Vérifiez que la base de données est accessible
3. En cas de problème, vous pouvez recréer la base manuellement :
```sql
DROP DATABASE babaevent;
CREATE DATABASE babaevent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
Puis redémarrez l'application.

### Port déjà utilisé
Changez le port dans `.env` ou arrêtez l'autre processus :
```bash
# Windows
netstat -ano | findstr :8000

# Linux/Mac
lsof -i :8000
```

## 🎯 Workflow de développement

1. **Modifier un modèle** dans `app/db/models.py`
2. **Redémarrer l'application** avec `python run.py`
3. **La migration s'applique automatiquement** ✨

Plus besoin de gérer manuellement les migrations !

## 🚀 Déploiement sur Railway

Ce projet est prêt pour être déployé sur Railway ! 🎉

### 🎯 Déploiement Rapide

1. **Push votre code** sur GitHub/GitLab/Bitbucket
2. **Créez un nouveau projet** sur [Railway](https://railway.app/)
3. **Connectez votre repository**
4. **Configurez les variables d'environnement** (voir ci-dessous)
5. **Déployez automatiquement** ! ✨

### 📝 Variables d'Environnement Requises

```env
ENVIRONMENT=production
SECRET_KEY=<générez-avec-openssl-rand-hex-32>
DATABASE_URL=${{MySQL.DATABASE_URL}}
CORS_ORIGINS=https://votre-frontend.com
DEBUG=false
```

### 📚 Guide Complet

Pour des instructions détaillées de déploiement, consultez **[DEPLOYMENT.md](./DEPLOYMENT.md)**

### ✅ Fonctionnalités Production-Ready

- ✅ **Health Checks** automatiques sur `/health`
- ✅ **Logging** structuré avec rotation
- ✅ **CORS** configuré et sécurisé
- ✅ **Validation** de la SECRET_KEY en production
- ✅ **Migrations** automatiques au démarrage
- ✅ **Error Handling** global
- ✅ **Docs API** désactivées en production
- ✅ **Connection Pooling** optimisé
- ✅ **Multi-workers** support

### 🔒 Sécurité

- Secret key validation
- CORS restrictif
- Passwords hashés avec bcrypt
- JWT tokens sécurisés
- Variables d'environnement protégées

### 📊 Monitoring

Railway fournit :
- Logs en temps réel
- Métriques de performance
- Alertes automatiques
- Health check monitoring

---

Pour déployer sur **d'autres plateformes** (Heroku, DigitalOcean, etc.) :

```bash
# Production avec Uvicorn
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
```
