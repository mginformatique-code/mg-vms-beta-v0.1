# Chapitre 28 — Grille de responsabilités

> **Version** : v1.0 · **Date** : 2026-07-24

Qui fait quoi dans l'écosystème MG-VMS ? Ce chapitre formalise les responsabilités par acteur.

## 28.1 Équipe core MG-VMS

**Responsable de** :
- Le noyau (~5000 lignes cible).
- Les 6 plugins officiels bundle.
- Le Plugin Manager.
- Le SDK plugins (Python d'abord, JS/Go/Rust/C# ensuite).
- Le SDK clients.
- Le Marketplace + review process.
- La documentation officielle (site + cahier des charges).
- Les releases (versioning, changelog, migration guides).
- Le support commercial (contrats maintenance).
- Les formations et certifications.

## 28.2 Développeurs plugins tiers

**Responsable de** :
- Leur plugin (code, docs, tests, changelog).
- Le support à leurs utilisateurs (channel Discord dédié).
- La compat avec le range core déclaré dans manifest.
- La sécurité de leur code (audit, signature GPG).
- La réponse aux CVE dans un délai raisonnable (7 jours pour critique).

## 28.3 Intégrateurs (Marc)

**Responsable de** :
- La pose physique et le paramétrage réseau chez client.
- Le choix des plugins pour chaque cas client.
- La formation opérateur (Sophie) chez client.
- Le support niveau 1 (réponse à Sophie/Karim en cas de doute).
- La sauvegarde régulière + tests restore.

## 28.4 Administrateurs (Karim)

**Responsable de** :
- La configuration RBAC (users, rôles, sites).
- L'audit de sécurité (revue régulière `db.audit_logs`).
- La conformité RGPD (rétention, exports, réponses demandes).
- Les mises à jour (test staging → prod).
- Le monitoring santé (dashboards Grafana).

## 28.5 Opérateurs (Sophie)

**Responsable de** :
- Surveillance quotidienne.
- Traitement des alertes.
- Signalement des incidents à l'admin.
- Ne PAS toucher à la configuration (permissions RBAC l'empêchent).

## 28.6 Utilisateurs finaux / clients

**Responsable de** :
- Fournir accès physique + réseau à l'intégrateur.
- Payer le contrat de maintenance.
- Renouveler la certification RGPD des utilisateurs.

## 28.7 Communauté

**Rôle** :
- Signaler bugs (issues GitHub).
- Contribuer traductions.
- Publier plugins.
- Aider sur Discord communautaire.
- Ratings + reviews Marketplace.

## 28.8 Escalade

En cas d'incident critique en prod :
1. Opérateur signale à l'admin.
2. Admin diagnostique via /diagnostics.
3. Si non-résolu 30 min → contact intégrateur.
4. Si non-résolu 2h → contact éditeur (contrat maintenance).

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
