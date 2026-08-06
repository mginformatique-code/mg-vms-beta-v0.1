# MG-VMS · ROADMAP v0.5.1.b (réalignement produit)

**Vision produit** : MG-VMS n'est pas une collection de pages, c'est une **suite
Control Center** avec 8 centres spécialisés, cohérente et complète, comparable
en approche à Milestone XProtect / Nx Witness / Synology Surveillance Station.

**Maturité globale actuelle** : **~62 % → RC v1.0** *(recalibrée v0.5.1.b)*

## Décomposition (poids relatifs recalibrés)

| Domaine | Poids | Avancement | Contribution | Δ vs estim. précédente |
|---|---:|---:|---:|---:|
| Pipeline IA | 12 % | 90 % | 10.8 | -0.4 (9/10) |
| Camera Device Layer | 10 % | 95 % | 9.5 | +1.0 (9.5/10) |
| Plugin System | 8 % | 90 % | 7.2 | +0.8 (9/10) |
| Latence acquisition | 8 % | 90 % | 7.2 | inchangé |
| UX (Centers unifiés) | 10 % | 85 % | 8.5 | +2.5 (8.5/10) |
| Sécurité | 8 % | 80 % | 6.4 | inchangé |
| Déploiement | 6 % | 75 % | 4.5 | -0.5 (7.5/10) |
| **Observabilité (nouveau)** | 10 % | 25 % | 2.5 | ⚠ nouveau domaine 1er ordre |
| Monitoring temps réel | 5 % | 30 % | 1.5 | -1.5 (6.5/10) |
| **Documentation** | 8 % | **40 %** | 3.2 | +2.5 (4/10, poids augmenté) |
| Tests régression | 5 % | 65 % | 3.3 | +0.3 |
| Workflow automation | 5 % | 40 % | 2.0 | nouveau |
| Drivers constructeurs | 5 % | 45 % | 2.3 | inchangé |
| **TOTAL** | **100 %** | | **≈62 %** | |

L'observabilité passe en domaine de 1er ordre (10 %). La documentation est revalorisée
en poids (8 % au lieu de 4 %) et en criticité (bloquant pour RC).

---

## 🎯 Les 8 Centers (identité produit)

Toute nouvelle page appartient à EXACTEMENT un Center. Un Center = un domaine, une couleur, un rôle.

| Center | Rôle | Statut |
|---|---|---|
| 🏠 **Dashboard** | Vue globale, points d'entrée | 60 % (Dashboard existant à moderniser) |
| 📹 **Camera Center** | Tout sur UNE caméra (11 onglets) | 85 % (v0.5.0.a/b) |
| ⚙️ **Pipeline Center** | Traitement vidéo + IA (10 onglets) | 80 % (v0.5.0.a) |
| 🧩 **Plugin Center** | Installed / Marketplace / Config / Runtime / Logs / SDK | 40 % (fragmenté) |
| 🖥️ **Operations Center** | Santé système, Docker, GPU, Mongo, go2rtc — répond au *"Pourquoi ?"* | **25 %** — priorité |
| 🔔 **Event Center** | Événements / ANPR / alertes / logs corrélés | 50 % (pages existantes non unifiées) |
| 🎬 **Recording Center** | Recherche + lecture enregistrements | 60 % (Timeline existant) |
| ⚙️ **Settings Center** | Configuration générale, utilisateurs, sécurité | 55 % |

---

## Roadmap produit réorganisée

### v0.5.1 · **Production Ready** *(en cours)*
Objectif : socle client pilote sécurisé + expérience d'accueil pro.

- ✅ v0.5.1.b · HTTPS + Nginx + docker-compose.prod + audit sécurité *(livré)*
- ⏳ v0.5.1.a · Welcome Center + menu final 7 items *(prochaine session)*
- ⏳ v0.5.1.c · **Documentation d'architecture minimale** (ADR pour décisions v0.4.3/v0.4.6, guide install, README refondu)
- ⏳ v0.5.1.d · Health backend endpoints (`mongo_ok`, `go2rtc_ok`, `gpu_percent`, `vram_percent`) pour alimenter le HealthBanner v0.5.0.b

### v0.6 · **Operations Center** *(le grand chantier observabilité)*
Objectif : répondre au *"Pourquoi ?"* — pas seulement au *"Combien ?"*.

- Camera Wizard (assistant ajout caméra avec probe automatique)
- Operations Center MVP : GPU/CPU/RAM/VRAM temps réel + historique 24h
- **Corrélation événements** : "cette caméra est passée à 2 FPS car GPU=97 % à cet instant"
- Alertes proactives (GPU>90 %, Mongo latence>1s, caméra offline>30s, disk<10 %)
- Drivers Axis + Hanwha + Uniview (compléter la matrice constructeur)
- Historique métriques Prometheus-like (série temporelle Mongo TS ou InfluxDB embedded)

### v0.7 · **Workflow Center**
Objectif : automation métier riche.

- Moteur Workflow graphique complet (SI plaque → ALORS portail + notif + bookmark + clip + spotlight)
- Scénarios pré-packagés (parking, sortie de secours, contrôle d'accès, ANPR liste noire)
- Triggers cross-Center (caméra → workflow → événement → notification)

### v0.8 · **Plugin Marketplace**
Objectif : écosystème plugin extensible par des tiers.

- Plugin Center unifié final (Marketplace, versioning, sandbox, signature)
- SDK plugin documenté avec templates prêts (FrameAnalyzer, PlateRecognizer, EventConsumer)
- Certification plugin (tests de charge automatisés, quarantaine si latence excessive)

### v0.9 · **Performances & Stress**
Objectif : preuves de scale mesurables sur RTX A2000.

- Benchmarks GPU réels 1/10/30/50 caméras (VRAM, FPS, latence bout-en-bout)
- Optimisations révélées par les bench (potentiellement TensorRT, batching YOLO, sub-streams IA)
- Documentation performances complète

### v1.0-RC → v1.0 Stable
- Audit sécurité complet externe (`security_audit_agent`)
- Audit régression complet UI+API (`testing_agent_v3_fork`)
- Release notes + migration guide + guide de déploiement client final
- 60 jours de stabilisation sur pilote client réel

---

## 🐛 Dette technique bloquante RC (à traiter dans v0.5.1 - v0.9)

| Item | Impact | Phase |
|---|---|---|
| Rate-limit brute-force casse CI (récur. 5 forks) | Tests régression fragiles | v0.5.1 |
| Health backend endpoints manquants | HealthBanner UI incomplète | v0.5.1 |
| CSP `'unsafe-inline'` (Tailwind runtime) | Sécurité 8→10 | v0.8 |
| Refresh token JWT + rotation | Sécurité 8→10 | v0.7 |
| Refactor `routers.py` monolithique | Maintenabilité | v0.6 |
| `analyze_image_local` hardcode `enabled_plugins` | UX upload manuel | v0.6 |
| Tests RTL réels (rendu vs invariants) | Confiance rendu | v0.6 |
| Backup MongoDB chiffré scripté | Production | v0.9 |
| Pipeline metrics rolling window imprécis | Diagnostic | v0.6 |
| `pip-audit` / `npm audit` CI | Sécurité | v0.7 |

---

## Contraintes absolues (invariantes v0.5.1 → v1.0)

- ❌ Ne pas casser pipeline IA (v0.4.3 · 12 tests iso stricts)
- ❌ Ne pas casser Camera Device Layer (v0.4.6 · 22 tests)
- ❌ Ne pas casser Pipeline/Camera Center (v0.5.0.a/b · 64 tests)
- ❌ Ne pas casser Docker / Mongo / go2rtc
- ✅ Chaque nouvelle page appartient à UN des 8 Centers (jamais isolée)
- ✅ Chaque tranche = audit non-régression + tests + rapport + doc + roadmap + score

---

## Prochaine session : choix

**Recommandation** : v0.5.1.a **Welcome Center + Menu final 7 items** — c'est ce qui rend visible tout ce qu'on a construit et donne l'impression de suite Control Center dès l'ouverture. Ça change la perception du produit sans nouvelle brique lourde.

**Alternative** : v0.5.1.c **Documentation ADR + README architecture** — moins glamour, mais évite que le "pourquoi" architectural se perde.
