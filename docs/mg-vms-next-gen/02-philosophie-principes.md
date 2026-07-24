# Chapitre 2 — Philosophie & principes

> **Version** : v1.0 · **Date** : 2026-07-24 · **Statut** : brouillon en cours de validation
> **Auteur** : équipe MG-VMS · **Reviewers** : *à compléter*
> **Chapitres liés** : `01-vision-positionnement` (le pourquoi) · `04-architecture-cible` (le comment technique) · `20-diagnostics-intelligents` (application concrète)

Ce chapitre formalise la **philosophie produit** de MG-VMS Next Generation et la transforme en **règles opposables** — c'est-à-dire des règles qu'un développeur, un PM ou un architecte peut invoquer en revue pour refuser une décision qui les viole. Ces règles ne sont pas des suggestions : ce sont des **contrats internes** qui gouvernent chaque évolution du produit.

---

## 2.1 Manifeste

MG-VMS Next Generation est un **outil de sécurité professionnel**, pas une démo technique. Ses utilisateurs sont des opérateurs de PC sécurité, des installateurs sur site, des exploitants multi-site — pas des ingénieurs Docker. Leur métier est de **surveiller, prévenir et intervenir**, pas de comprendre pourquoi le pipeline IA a régressé après un rebuild GPU.

Trois convictions guident chaque décision :

1. **Un VMS qui plante n'est pas un VMS.** Une caméra qui perd sa connexion, un module IA qui rate un modèle, un GPU qui sature — ces événements sont **normaux** dans la vie d'un système de vidéosurveillance. Ils ne doivent **jamais** dégrader l'expérience globale.
2. **Une fonction incompréhensible n'existe pas.** Si un opérateur ne comprend pas ce qu'un voyant rouge veut dire, si un installateur ne sait pas pourquoi une caméra reste offline, la fonction est cassée — même si elle « marche techniquement ».
3. **Un système fermé est un système mort.** MG-VMS doit s'ouvrir aux intégrations tierces (Home Assistant, MQTT, Node-RED, Slack…) par défaut, pas en option payante.

Ces trois convictions sont opérationnalisées par **trois piliers** et **quinze règles opposables** que le reste du chapitre détaille.

---

## 2.2 Les trois piliers

### 2.2.1 Pilier 1 — Simple pour l'utilisateur

**Définition** : un opérateur qui a suivi une formation d'une heure doit pouvoir utiliser 90% des fonctions courantes (live, recherche, alertes, export). Un installateur doit pouvoir configurer un site de 20 caméras en 30 minutes maximum.

**Ce que ça implique concrètement** :

- **Le mode Installateur** (chapitre 6) doit couvrir stockage + GPU + ONVIF + IA + users + notifications en 10-15 min sans intervention terminal.
- **Chaque action destructrice** est confirmée en langage clair (« Supprimer la caméra "Entrée principale" — 2 mois d'enregistrements seront conservés selon la rétention ») et jamais par un « OK / Cancel » technique.
- **Chaque erreur affichée** propose une action (« La caméra ne répond pas — [Retester la connexion] · [Voir le diagnostic] »).
- **Chaque page a un objectif unique.** Le mur vidéo affiche des caméras, il ne configure pas les alertes. Les alertes se filtrent, elles ne changent pas le layout du mur.
- **La configuration avancée est cachée par défaut**. Un opérateur ne voit pas les toggles « bytetrack lambda » ; ils sont dans un panneau « Avancé » collapsé.

**Anti-pilier** — ce qu'on refuse :
- Formulaires de plus de 15 champs sans regroupement logique.
- Messages d'erreur techniques bruts dans l'UI (`HTTP 500`, `KeyError: 'foo'`).
- Fonctions accessibles uniquement en ligne de commande sans équivalent UI.

### 2.2.2 Pilier 2 — Modulaire pour le développeur

**Définition** : chaque composant fonctionnel doit pouvoir être développé, testé, remplacé et déployé **indépendamment** des autres. Un dev qui touche à l'ANPR ne doit pas devoir comprendre le PTZ.

**Ce que ça implique concrètement** :

- **Chaque module IA** est un fichier `services/ai_modules/{name}.py` avec un contrat unique (`load()`, `analyze(frame_bgr, cam) -> ModuleResult`). Ajouter YOLO, ANPR ou un module « smoke detection » suit la même procédure.
- **Chaque route HTTP** vit dans `routes/{domain}.py`, jamais dans un `routers.py` monolithique (ADR-01).
- **Chaque intégration tierce** (SMTP, Discord, MQTT…) implémente la même interface `Notifier` avec `send()` + `test_connection()`.
- **Les tests d'un module** ne dépendent pas des autres modules. Un test ANPR ne charge pas YOLO. Un test WebRTC ne monte pas MongoDB.
- **La configuration** vit en un endroit unique (DB collection `settings`) accessible via API — pas de fichier `.ini` disséminé, pas de constante hard-codée.

**Anti-pilier** — ce qu'on refuse :
- Fichiers Python > 500 lignes en `services/` (au-delà, découper).
- Fonctions qui font 3 choses (SRP violé — Single Responsibility Principle).
- Imports circulaires (auth ↔ notifications sans lazy import).
- Configuration via multiples sources contradictoires (env + fichier + DB).

### 2.2.3 Pilier 3 — Stable en production

**Définition** : le système doit fonctionner **24/7** pendant des mois sans intervention humaine. Une panne composant (caméra, GPU, module IA, service externe) doit être **isolée** et **explicable**, jamais silencieuse ni cascadante.

**Ce que ça implique concrètement** :

- **Chaque appel réseau** a un timeout explicite (jamais de `timeout=None` implicite).
- **Chaque tâche asynchrone long-running** est encadrée par un `try/except` global qui la fait redémarrer, jamais mourir silencieusement (leçon v2.21.0 : `ai_loop` ne s'auto-désactive plus JAMAIS).
- **Chaque service externe** est protégé par un circuit breaker (5 échecs → ouvert 60 s).
- **Chaque erreur systémique** est journalisée en DB (`db.audit_logs`, `db.stream_lifecycle_journal`, `db.failed_operations`) — pas seulement en logs supervisor qui tournent.
- **Chaque voyant rouge dans l'UI** est cliquable et donne la cause probable en français, jamais un statut opaque.
- **Chaque déploiement** est réversible en 1 commande (`git checkout <tag> && docker compose up -d`).

**Anti-pilier** — ce qu'on refuse :
- `except Exception: pass` sans log ni action.
- Cache in-memory sans TTL ni invalidation explicite (fuite garantie).
- Modification de schéma DB sans migration versionnée.
- Fonction critique qui dépend d'un service externe sans fallback.

---

## 2.3 Les quinze règles opposables

Chaque règle a un identifiant `RXX`, un libellé court, un scope d'application et un **critère de vérification** au review. Une règle enfreinte = PR bloquée.

### R01 — Aucun composant ne cascade sa panne

**Scope** : architecture, services asynchrones.
**Règle** : une panne de composant X (caméra, GPU, IA, storage, notif…) ne doit **jamais** dégrader le fonctionnement d'un composant Y non-dépendant.
**Vérification** : test d'acceptation obligatoire du module — simuler la panne du composant X, vérifier que Y continue à fonctionner.
**Exemple d'application** : `ai_engine._load_models` échec ⇒ `ai_loop` continue à tourner et retente (v2.21.0, ADR-05).

### R02 — Tout voyant rouge est explicable en 1 clic

**Scope** : UI, diagnostics.
**Règle** : aucun statut négatif dans l'UI (badge rouge, alerte, warning) ne peut être opaque. Un clic doit ouvrir la cause probable en langage humain + une action recommandée.
**Vérification** : audit UI — parcourir toutes les pages, vérifier que chaque élément « rouge » a un tooltip ou un dialog explicatif.
**Exemple** : caméra offline → dialog diagnostic montre « Cause probable : timeout RTSP (12 s dépassé) · Dernière tentative : il y a 45 s · Action : [Retester la connexion] · [Voir les logs] ».

### R03 — go2rtc est l'unique gateway RTSP

**Scope** : services vidéo.
**Règle** : le backend n'ouvre **jamais** de connexion RTSP directe vers une caméra IP en production. Seul go2rtc parle aux caméras. Tous les consommateurs internes (viewer, recorder, IA) passent par `rtsp://go2rtc:8554/cam_XXX`.
**Vérification** : garde-fou dans `frame_source.start()` (ValueError si URL non-go2rtc) + linter customisé qui refuse les patterns `rtsp://<ip>` en dur.
**Exception explicite** : `ffprobe` ponctuel lors du test-connectivity, ou bypass `allow_direct=True` pour outillage de test.

### R04 — La DB est source de vérité unique

**Scope** : données persistantes.
**Règle** : aucun état applicatif persistant ne vit ailleurs que dans MongoDB. Les exceptions autorisées sont : segments vidéo (Storage Manager), modèles IA (téléchargés au boot), `go2rtc.yaml` limité aux caméras démo statiques.
**Vérification** : audit des fichiers de config — aucun fichier ne doit référencer une caméra utilisateur, un user, une plaque, un événement.
**Exemple** : v2.22.0 réconciliation DB ↔ go2rtc (ADR-03).

### R05 — Aucun secret en clair sur disque

**Scope** : sécurité.
**Règle** : mots de passe, tokens, clés API — jamais persistés en clair. Chiffrement Fernet (clé en env `MGVMS_ENCRYPTION_KEY`) avant écriture DB.
**Vérification** : test unitaire qui insère un mot de passe et vérifie que la représentation Mongo est bien chiffrée. Grep CI qui refuse `password.*=.*"[a-zA-Z]"` en source.
**Exception** : credentials de test dans `/app/memory/test_credentials.md` (fichier hors Docker, jamais déployé).

### R06 — Aucun appel réseau sans timeout

**Scope** : code backend.
**Règle** : tout appel `httpx`, `requests`, `motor`, `subprocess`, SOAP a un timeout explicite. `timeout=None` interdit sauf justification en revue.
**Vérification** : linter custom `ruff` règle `MGVMS001` qui detecte les appels sans timeout. CI bloque si violation.
**Défauts recommandés** : HTTP interne 6 s · ONVIF 25 s · ffprobe 12 s · Mongo 10 s · notifs externes 15 s.

### R07 — Aucune boucle asyncio ne meurt silencieusement

**Scope** : services long-running.
**Règle** : chaque task asyncio (ai_loop, camera_status_loop, recorder_supervisor…) est encadrée par `try/except Exception` global. Sur exception, log + increment métrique erreur + `continue` — jamais `return`, `raise` ni `sys.exit`.
**Vérification** : test d'acceptation par boucle — patcher une méthode interne pour raise, vérifier que la boucle continue au cycle suivant.
**Exemple** : v2.21.0 refonte `ai_loop`.

### R08 — Toute action destructrice est réversible ou confirmée

**Scope** : UI + API.
**Règle** :
- Réversible : soft-delete par défaut (flag `deleted_at`), corbeille 30 j, restauration possible.
- Sinon : confirmation explicite avec libellé humain + case à cocher « je comprends les conséquences » pour actions critiques (suppression site, purge enregistrements).
**Vérification** : audit UI + endpoints — chaque DELETE HTTP a une confirmation UI (dialog, pas juste un toast).
**Exception** : sessions expirées, événements > rétention (purge automatique documentée).

### R09 — Toute action système est audité en DB

**Scope** : administration.
**Règle** : chaque action utilisateur admin ou technicien (login, modif config, création/suppression caméra, resync go2rtc, migration storage…) écrit une entrée dans `db.audit_logs` avec `{user, action, target, details, ip, timestamp}`. Rétention 1 an minimum.
**Vérification** : test d'acceptation par endpoint POST/PUT/DELETE — assert `db.audit_logs.count_documents({action: ...})` incrémenté.

### R10 — Aucune régression sans test

**Scope** : développement.
**Règle** : chaque bug résolu ⇒ test d'acceptation ajouté qui reproduit le bug avant fix et passe après. Le test devient un anti-régression permanent.
**Vérification** : pull request refusée si bug fix sans test associé. Coverage minimum 70% sur `services/` et `routes/` en v3.0.
**Exemples** : `test_iter30_ai_health_and_gateway.py` (v2.21.0), `test_iter31_streams_sync.py` (v2.22.0).

### R11 — Chaque module fonctionnel a sa spec avant son code

**Scope** : processus de développement.
**Règle** : aucun module fonctionnel du cahier des charges n'est développé sans son chapitre validé au préalable (User stories + API + Modèle de données + Modes dégradés + Tests d'acceptation). Le code suit le doc, pas l'inverse.
**Vérification** : chaque PR de nouvelle feature référence le chapitre validé du cahier. PM ou architecte review le doc **avant** le sprint dev.
**Corollaire** : les chapitres validés sont taggés Git (`docs/chapter-XX-v1`). Toute évolution suit `-v2`, `-v3`.

### R12 — Chaque module IA est activable indépendamment

**Scope** : moteur IA.
**Règle** : YOLO, ANPR, Face, Smoke, Fire, PPE, Counting, Loitering, CrossLine, Zone — chaque module a un toggle par caméra (`cameras.ai_modules.{name}.enabled`). Désactiver un module désactive uniquement lui, jamais les autres. Le crash de chargement d'un module ne cascade pas.
**Vérification** : test d'acceptation « toggle YOLO off pour cam_1 ⇒ ANPR de cam_1 continue, YOLO de cam_2 continue ».
**Exemple** : ADR-05.

### R13 — Aucune configuration ne survit à un reset propre

**Scope** : maintenance.
**Règle** : la commande `docker compose down -v && docker compose up -d` doit produire un système fonctionnel identique à une installation neuve, en 1 minute. Toute persistance qui n'est pas dans les volumes Docker déclarés est un bug.
**Vérification** : test CI — reset complet, boot, connexion admin, vérifier caméras démo présentes.

### R14 — Chaque intégration tierce est optionnelle

**Scope** : services externes (SMTP, Discord, MQTT, LDAP, OIDC…).
**Règle** : le VMS doit démarrer et fonctionner **sans aucune** intégration configurée. Chaque intégration a un flag `enabled: false` par défaut. Sa panne dégrade seulement la fonctionnalité qu'elle porte, jamais le core.
**Vérification** : test d'acceptation « démarrer avec seulement Mongo + go2rtc + backend + frontend, aucun SMTP/MQTT/etc — le système fonctionne, les alertes s'accumulent en DB avec badge "N alertes non délivrées" ».

### R15 — Toute décision structurante est un ADR

**Scope** : gouvernance produit.
**Règle** : les décisions d'architecture, de sécurité ou de compat sont écrites comme ADR (Architecture Decision Record) dans le cahier des charges, avec `Contexte / Décision / Conséquences / Alternatives rejetées`. Un dev qui « prend une décision différente » sans nouvel ADR viole le contrat.
**Vérification** : chaque chapitre a une section ADR. Chaque changement d'architecture ⇒ nouvel ADR ou révision de l'existant.
**Exemples actuels** : ADR-01 à ADR-07 du chapitre 4.

---

## 2.4 Anti-patterns explicitement refusés

Ces patterns sont **interdits en production** MG-VMS. Ils apparaissent souvent dans les VMS grand public — leur absence est un différenciateur.

### AP-01 — Le voyant rouge orphelin

*« La caméra est offline. »*
**Interdit.** Doit être : *« La caméra est offline depuis 3 min. Cause probable : timeout RTSP (auth refusée à la 3e tentative). Dernière connexion réussie il y a 2 h. [Retester] [Diagnostic complet] »*.

### AP-02 — Le rebuild qui casse tout

*« Après le rebuild GPU, plus rien ne marche, même en CPU. »*
**Interdit.** Chaque composant a un `try/except` de chargement, un flag `enabled` runtime, une commande de bypass (ex. `MGVMS_AI_FORCE_CPU=1`). Un rebuild ne peut pas suicider silencieusement une boucle.

### AP-03 — Le formulaire monstre

Écran de création caméra avec 40 champs visibles, dont 30 concernent 1% des cas.
**Interdit.** Structuration en étapes (wizard) avec section « Avancé » collapsée par défaut. Les valeurs par défaut couvrent 90% des caméras.

### AP-04 — Le patch invisible

Modification de comportement sans changelog, sans test, sans ADR. « Ça marche mieux comme ça sur ma machine. »
**Interdit.** R10 + R15.

### AP-05 — La dépendance silencieuse

*« Ça marche seulement si vous avez configuré le SMTP.  »*
**Interdit.** Une dépendance non-satisfaite doit être **détectée au boot**, signalée dans `/api/health/ready`, et documentée en UI (« Notifications mail désactivées : SMTP non configuré [Configurer] »).

### AP-06 — Le mode dégradé caché

Le système continue mais différemment sans le signaler à l'utilisateur.
**Interdit.** Tout fallback (GPU→CPU, WebRTC→MJPEG, SMTP→queue) affiche un badge visible dans l'UI (« CPU fallback », « MJPEG fallback ») + est loggé.

### AP-07 — La config parallèle

Modifier un paramètre en env, en base, en fichier — 3 sources contradictoires.
**Interdit.** Une donnée = une source. Les env sont pour bootstrap uniquement, la DB prend le relais dès le premier démarrage.

### AP-08 — L'export CSV Excel-incompatible

*« Il faut ouvrir le CSV dans un éditeur pour changer l'encoding. »*
**Interdit.** BOM UTF-8 systématique en tête de fichier. Séparateur `,`. Guillemets doubles. Dates ISO 8601. Testé sur LibreOffice ET Excel.

### AP-09 — La feature en beta permanente

Fonction annoncée « expérimentale » qui le reste 3 ans.
**Interdit.** Une feature en beta a une **date de sortie de beta** (max 6 mois) documentée. Après cette date : soit elle sort en stable, soit elle est retirée.

### AP-10 — Le log qui ment

Log INFO alors que l'action a échoué. Log WARNING masquant une erreur critique.
**Interdit.** Niveaux logs stricts :
- `DEBUG` — détail dev, désactivé prod.
- `INFO` — action nominale réussie.
- `WARNING` — dégradation attendue (fallback, retry).
- `ERROR` — anomalie qui nécessite investigation, jamais silencieuse.
- `CRITICAL` — panne système bloquante (base morte, disque plein, service externe indispensable KO).

---

## 2.5 Grille d'arbitrage — quand les règles conflictent

Les règles peuvent parfois entrer en tension. Exemple : **R08 (action confirmée)** vs **P1 (Simple utilisateur)** — trop de confirmations tuent l'usabilité. La grille suivante donne la priorité :

**Ordre de priorité (du plus fort au plus faible)** :

1. **Sécurité** (R05, R09) — jamais compromise.
2. **Stabilité** (R01, R07, R14) — jamais dégradée pour un gain UX temporaire.
3. **Simplicité utilisateur** (P1, R02, R08) — prioritaire sur la modularité.
4. **Modularité développeur** (P2, R03, R04, R12) — prioritaire sur l'élégance du code.
5. **Élégance du code / performance** — dernière priorité.

**Exemple d'arbitrage** : ajouter une option de config pour désactiver le chiffrement Fernet des mots de passe caméra ?
- Argument pour : modularité, cas d'usage lab.
- Argument contre : R05 (sécurité).
- **Verdict** : refusé. Sécurité prime.

**Autre exemple** : forcer une confirmation à chaque snapshot pris ?
- Argument pour : R08 (traçabilité).
- Argument contre : P1 (simple).
- **Verdict** : le snapshot n'est pas destructif. Confirmation non requise. Le snapshot est audité (R09) — suffisant.

---

## 2.6 Application aux décisions passées

Cette section documente comment les principes ci-dessus ont gouverné des décisions concrètes prises depuis v2.13.

| Version | Décision | Règle appliquée |
|---|---|---|
| v2.13.0 | Miniatures HD 1280×720 au lieu de crops < 100 px | P1 (simple) : identifier une plaque à l'œil nu |
| v2.14.0 | Diagnostic caméra avec cause probable en français | R02 (voyant rouge explicable) |
| v2.16.2 | Cache `_ensure_variants_cached` throttle 60 s | R01 (thundering herd = cascade) |
| v2.17.0 | Suppression du `register_camera_stream` auto sur probe fail | R01 (cascade viewers/IA) + R08 (action destructrice cachée) |
| v2.18.0 | frame_source subprocess ffmpeg GPU dédié | R03 (go2rtc gateway) + P2 (modulaire) |
| v2.20.0 | Probe non-invasif (`bytes_recv` delta au lieu de frame.jpeg) | R01 (churn sessions caméra) |
| v2.21.0 | `ai_loop` résilient + `/api/diagnostics/ai-health` | R02 + R07 (jamais silencieux) |
| v2.22.0 | Réconciliation DB ↔ go2rtc + bouton "Resynchroniser" | R04 (DB source unique) + R02 (drift explicable) |

Ces décisions ne sont pas des « bonnes idées ponctuelles » — elles sont des **applications directes** des règles. Elles auraient été prises de la même façon par n'importe quel dev qui applique R01→R15.

---

## 2.7 Application aux décisions futures — checklist review

Chaque pull request qui ajoute une feature significative passe cette checklist en revue. Une case non cochée = revue bloquée.

**Simplicité utilisateur** :
- [ ] Un opérateur non-technicien peut utiliser cette fonction sans lire de doc ?
- [ ] Les erreurs affichées proposent une action ?
- [ ] La configuration avancée est cachée par défaut ?
- [ ] Aucun jargon technique dans l'UI (HTTP codes, noms de classes Python, IDs bruts) ?

**Modularité** :
- [ ] Le code métier est dans `services/` ou `routes/`, jamais dans un fichier > 500 lignes ?
- [ ] Le module a une interface publique claire (fonctions async top-level) ?
- [ ] Les tests du module ne dépendent pas des autres modules ?
- [ ] La configuration vit en DB, pas en fichier local ?

**Stabilité** :
- [ ] Tous les appels réseau ont un timeout ?
- [ ] Les boucles asyncio ont un `try/except` global ?
- [ ] Les services externes sont protégés par circuit breaker ou retry backoff ?
- [ ] Les erreurs sont journalisées en DB (`audit_logs` / journal spécifique) ?
- [ ] Un fallback existe si la dépendance principale est KO ?

**Sécurité** :
- [ ] Les secrets sont chiffrés Fernet avant persistence ?
- [ ] Les entrées utilisateur sont validées Pydantic ?
- [ ] Les endpoints admin exigent `require_permission(...)` ?
- [ ] Les mots de passe ne sont jamais loggés ?

**Documentation** :
- [ ] Le chapitre correspondant du cahier des charges est à jour ?
- [ ] Un ADR est créé si la décision est structurante ?
- [ ] Le CHANGELOG mentionne la feature ?
- [ ] Un test d'acceptation existe (pas juste un test unitaire) ?

---

## 2.8 Métriques d'adhésion aux principes

Ces métriques quantifient à quel point le produit respecte sa propre philosophie. Elles sont calculées automatiquement et publiées en interne trimestriellement.

**Simplicité utilisateur (P1)** :
- Taux d'installation réussie sans support en < 15 min : cible ≥ 85%.
- Taux de résolution des voyants rouges par l'utilisateur seul (sans ticket support) : cible ≥ 80%.
- Nombre moyen de clics pour actions courantes (voir alertes, exporter journal) : cible ≤ 3.

**Modularité développeur (P2)** :
- Nombre de fichiers `services/` > 500 lignes : cible **0**.
- Nombre d'imports circulaires : cible **0**.
- Temps moyen d'ajout d'un module IA (mesure interne) : cible ≤ 2 jours.
- Coverage tests `services/` : cible ≥ 70%.

**Stabilité production (P3)** :
- MTBF système : cible ≥ 30 j.
- Taux d'incidents avec cause probable identifiée automatiquement : cible ≥ 90%.
- Taux d'incidents avec cascade (panne composant → autre composant) : cible **0**.
- Temps moyen de récupération après reboot : cible ≤ 60 s.

**Sécurité** :
- Nombre d'endpoints sans `require_permission` : cible **0**.
- Nombre de secrets en clair détectés en DB (audit trimestriel) : cible **0**.
- Taux d'actions admin sans audit log : cible **0**.

---

## 2.9 Ce que ce document n'est PAS

Pour éviter les malentendus :

- **Ce n'est pas une bible immuable.** Les règles évoluent avec le produit. Chaque évolution passe par un ADR et une révision du chapitre.
- **Ce n'est pas un ralentisseur.** Un dev qui applique les règles produit du code robuste plus vite qu'un dev qui débogue ses shortcuts pendant 3 semaines.
- **Ce n'est pas une exigence de perfection.** Les écarts existants (§ 4.11 chapitre 4) sont **documentés** — donc gérés. Ce qui est interdit, c'est l'écart **silencieux**.
- **Ce n'est pas un frein à l'innovation.** Les 3 piliers autorisent explicitement des expériences (feature flag, beta timée) — à condition qu'elles ne violent pas les invariants sécurité et stabilité.

---

## 2.10 Prochaines étapes de conception

Chapitres qui approfondissent cette philosophie sur des sujets précis :

- **Chapitre 6 — Mode Installateur** : R02 + P1 appliqués au bootstrap.
- **Chapitre 11 — Moteur IA modulaire** : R12 (modules indépendants) appliqué à l'IA.
- **Chapitre 20 — Diagnostics intelligents** : R02 (voyants explicables) formalisé.
- **Chapitre 22 — Administration RBAC** : R05 + R09 appliqués à la sécurité.
- **Chapitre 26 — Roadmap** : plan de rattrapage des écarts v2.22.0 vs cible v3.0.

---

## Annexes

### A. Résumé opposable

| ID | Règle | Composant vérificateur |
|---|---|---|
| R01 | Aucun composant ne cascade sa panne | Tests d'acceptation par module |
| R02 | Tout voyant rouge est explicable en 1 clic | Audit UI |
| R03 | go2rtc est l'unique gateway RTSP | `frame_source.start()` guard + linter |
| R04 | La DB est source de vérité unique | Audit config files + `/streams-sync` |
| R05 | Aucun secret en clair sur disque | Test insertion + CI grep |
| R06 | Aucun appel réseau sans timeout | Linter `MGVMS001` |
| R07 | Aucune boucle asyncio ne meurt silencieusement | Test raise-then-continue |
| R08 | Toute action destructrice est réversible ou confirmée | Audit UI |
| R09 | Toute action système est auditée | Test count audit_logs |
| R10 | Aucune régression sans test | Review PR |
| R11 | Chaque module a sa spec avant son code | Review PR + tag Git chapitre |
| R12 | Chaque module IA activable indépendamment | Test toggle par module |
| R13 | Aucune config ne survit à un reset propre | Test CI reset |
| R14 | Chaque intégration tierce est optionnelle | Test démarrage minimal |
| R15 | Toute décision structurante est un ADR | Review PR |

### B. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : 3 piliers · 15 règles · 10 anti-patterns · grille d'arbitrage · checklist review · métriques d'adhésion |
