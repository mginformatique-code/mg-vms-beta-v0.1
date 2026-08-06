# Marketplace Test

Plugin **FrameAnalyzer** pour MG-VMS.

## Installation

```bash
cp -r marketplace-test /app/data/plugins/
sudo supervisorctl restart backend
```

## Configuration

Éditez `config/schema.json` pour déclarer les champs configurables par
l'utilisateur (le formulaire est généré automatiquement par l'UI Plugin Manager).

## Développement

Ouvrez `plugin.py` et implémentez la méthode principale de votre interface.
