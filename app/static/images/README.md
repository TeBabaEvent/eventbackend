# Images Statiques - BABA Event

Ce dossier contient les images utilisées par le backend pour les emails et PDFs.

## Logo

Ajoutez votre logo ici en **format PNG** (recommandé) ou JPG.

### Fichiers supportés :
- `logo.png` (recommandé - supporte la transparence)
- `logo.jpg` / `logo.jpeg`

### Spécifications recommandées :
- **Taille** : 400x200 pixels (ou ratio similaire)
- **Format** : PNG avec transparence
- **Poids** : < 100 KB pour les emails

### Conversion SVG → PNG

Si vous avez un logo SVG, convertissez-le en PNG :

**Option 1 - En ligne :**
- https://svgtopng.com
- https://cloudconvert.com/svg-to-png

**Option 2 - Avec Inkscape (gratuit) :**
```bash
inkscape logo.svg --export-png=logo.png --export-width=400
```

**Option 3 - Avec Python (cairosvg) :**
```python
import cairosvg
cairosvg.svg2png(url="logo.svg", write_to="logo.png", output_width=400)
```

## Utilisation

Une fois `logo.png` ajouté ici, il sera automatiquement :
- Embarqué dans les emails de confirmation
- Affiché dans les PDFs de billets

⚠️ **Note** : Les emails ne supportent pas le format SVG. Utilisez PNG ou JPG.

