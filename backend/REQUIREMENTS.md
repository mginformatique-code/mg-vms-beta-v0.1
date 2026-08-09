# Backend Python dependencies · MG-VMS v1.0-rc4

Trois fichiers, trois rôles distincts. Cette structure est **volontaire** et
**ne doit pas être fusionnée** — chaque fichier a son cas d'usage.

## 📦 `requirements.txt` (247 lignes · Freeze production)

**C'est le SEUL fichier installé dans l'image Docker de production.**

Contenu : freeze complet et déterministe (résultat d'un `pip freeze` où les
dépendances de base + IA ont été résolues ensemble une fois pour toutes).
Toutes les transitives sont épinglées. Le résolveur pip standard passe sans
`--no-deps` et sans conflit.

Utilisé par :
- `backend/Dockerfile` → `pip install -r requirements.txt`
- Dev local complet → `pip install -r requirements.txt`

## 🧠 `requirements-ai.txt` (67 lignes · Spec source IA)

**Documentation haut-niveau de la stack IA/GPU cible** (torch cu124, ultralytics,
insightface, fast-alpr, onnxruntime-gpu…) avec justifications de chaque choix.

Ce fichier est une **spécification de référence**, PAS un fichier à installer
directement en production (les versions figées finales sont dans
`requirements.txt`, potentiellement différentes des versions cibles ici après
résolution).

Utilisé par :
- Consultation lors des upgrades majeurs (« quelle version de torch cible-t-on ? »)
- Régénération du freeze consolidé (voir procédure ci-dessous)
- Documentation à long terme des choix techniques

## 🛠️ `requirements-dev.txt` (26 lignes · Outils dev/CI)

**JAMAIS installé dans l'image Docker de production** (ligne 3 du fichier).

Contenu : pytest, pytest-xdist, ruff, black… outils qui n'ont RIEN à faire
dans le container prod.

Utilisé par :
- Développement local → `pip install -r requirements.txt -r requirements-dev.txt`
- CI/CD → tests + linting

## 🔄 Régénérer `requirements.txt` après un upgrade

Si un jour tu veux upgrader `torch` (par exemple 2.4.1 → 2.7.0) documenté dans
`requirements-ai.txt` :

```bash
# 1. Créer un env virtuel PROPRE
python3.11 -m venv /tmp/mgvms-freeze
source /tmp/mgvms-freeze/bin/activate

# 2. Installer base + AI ensemble (pip résout les conflits)
pip install --upgrade pip
pip install -r requirements-ai.txt \
    --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
# … ajouter ici les autres packages base non-AI (fastapi, motor, pydantic, etc.)

# 3. Regénérer le freeze consolidé
pip freeze > requirements.txt

# 4. Valider dans un build Docker
cd deploy-app && ./install.sh --check-only && docker compose build backend
```

⚠ Ne JAMAIS éditer `requirements.txt` à la main. Toujours passer par un
`pip freeze` déterministe.

## ❓ FAQ

**Q : Pourquoi le Dockerfile n'installe pas `requirements-ai.txt` en plus ?**
R : Parce que `requirements.txt` contient DÉJÀ toutes les libs IA (torch,
ultralytics, fast-alpr, paddleocr…) avec leurs versions figées après
résolution. Installer `requirements-ai.txt` par-dessus rétrograderait
certaines libs (les versions cibles y sont plus anciennes) et casserait
le runtime GPU.

**Q : Peut-on fusionner les 3 fichiers ?**
R : Non. Chacun a un rôle métier différent (freeze prod / spec IA / outils dev).
La séparation permet notamment de ne PAS installer pytest en production.
