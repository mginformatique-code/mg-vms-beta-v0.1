# Chapitre 23 — API publique & SDK

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `05-contrats-interfaces` · `11-plateforme-plugins`

Ce chapitre complète le chapitre 5 en approfondissant les **SDK officiels** — les bibliothèques que MG-VMS livre pour consommer son API publique. Contrairement au chapitre 11 (SDK **plugins**), ce chapitre parle des SDK **clients** (consommer le VMS depuis une app externe).

## 23.1 Périmètre

Un SDK client permet de :
- S'authentifier.
- Interroger toutes les ressources REST.
- S'abonner aux flux WebSocket temps-réel.
- Publier / consommer sur MQTT.
- Recevoir / valider les webhooks entrants.
- Upload de fichiers (photos face, imports CSV).

**Différence avec Plugin SDK** : le Plugin SDK tourne DANS MG-VMS. Le Client SDK tourne DEHORS (app mobile intégrateur, script analytics, dashboard tiers, bot IA).

## 23.2 Langages supportés

### v3.1
- **Python** (`mgvms-sdk`) — pip install. Async natif (`asyncio`) + version sync. Type hints complets. Python 3.10+.
- **JavaScript / TypeScript** (`@mgvms/client`) — npm install. Bundle browser + Node.js. React hooks (`@mgvms/react`).

### v3.2+
- **Go** (`github.com/mg-vms/go-sdk`) — pour outils CLI et intégrations serveur haute perf.
- **C#** (`MGVMS.Client` NuGet) — cible écosystème Microsoft (bridge Milestone, apps WPF/MAUI).
- **Rust** (`mgvms-rs` crates.io) — cible IoT industriel.

## 23.3 Design principles

- **Idiomatic** — chaque SDK suit les conventions de son langage (async Python, promises JS, contexts Go, tasks C#).
- **Type-safe** — Pydantic Python, TS types stricts, structs Go, records C#.
- **Auto-retry** — retry backoff intégré sur erreurs 5xx.
- **Offline-tolerant** — les callbacks WS reconnect automatiquement.
- **Documentation par exemple** — chaque endpoint a un snippet exécutable dans les docs.

## 23.4 CLI officiel `mgvms-cli`

Outil ligne de commande multiplateforme (compilé Go statique). Cas d'usage :
- Connexion à une instance : `mgvms-cli login https://vms.example.com`.
- Commandes admin sans UI : `mgvms-cli camera list`, `mgvms-cli plugin install yolo-detection`.
- Backup / restore : `mgvms-cli backup create --output=backup.tar.gz`.
- Dev plugin : `mgvms-cli plugin init/build/test/publish`.
- Diagnostic : `mgvms-cli diagnostic camera <id>`.

## 23.5 Compatibilité versions

- SDK v1.x supporte API `/api/v1/*`. Compatible avec toute version MG-VMS core `v3.x`.
- SDK v2.x sortira au moment du passage `/api/v2/*` (breaking changes majeurs).
- Deprecation policy : SDK v1.x supporté 24 mois après sortie v2.x.

## 23.6 Documentation

- **API Reference** — OpenAPI auto-généré (`/api/docs`).
- **Guides** — par langage, pas-à-pas (Hello World → cas avancés).
- **Cookbook** — recettes concrètes (ex. « déclencher une automatisation externe sur détection blacklist »).
- **Playground interactif** — Swagger UI + curl generator.

## 23.7 Tests

- TA-23.1 : `pip install mgvms-sdk` + Hello World < 5 lignes → liste caméras.
- TA-23.2 : `@mgvms/client` en React → hook `useMGVMSEvents` reçoit events temps-réel.
- TA-23.3 : `mgvms-cli plugin install yolo-detection` → installation réussie.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
