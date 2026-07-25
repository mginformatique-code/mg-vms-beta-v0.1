# Chapitre 6 — Mode Installateur

> **Version** : v1.0 · **Date** : 2026-07-24 · **Statut** : brouillon en cours de validation
> **Auteur** : équipe MG-VMS · **Reviewers** : *à compléter*
> **Chapitres liés** : `02-philosophie-principes` (R02 « aucun voyant rouge orphelin ») · `04-architecture-cible` (composants) · `10-ajout-camera` (détail ONVIF) · `16-storage-manager` (pools) · `17-gpu-manager` (bench CUDA) · `22-administration-rbac` (users)

Le Mode Installateur est le **différenciateur fondamental** de MG-VMS Next Generation. Il transforme la mise en service d'un serveur — traditionnellement 2 à 4 heures de navigation dans une douzaine d'écrans techniques sur Milestone / Genetec / Digifort — en un **assistant guidé de 10 à 15 minutes** qui livre un système entièrement fonctionnel.

Ce chapitre fige la vision, le parcours utilisateur, l'architecture technique et les tests d'acceptation de cet assistant.

---

## 6.1 Vision

### 6.1.1 Le problème actuel

L'installation d'un VMS professionnel typique suit ce parcours :

1. Installer le système d'exploitation (30 min)
2. Installer le VMS (30 min)
3. Ouvrir l'interface admin, se perdre 15 min dans les menus
4. Configurer manuellement le stockage (formatage disques, création pools, allocation) — 30 min
5. Installer les drivers GPU, tester CUDA, configurer TensorRT — 45 min
6. Lancer le scan caméras, saisir les credentials à la main — 30 min
7. Configurer chaque caméra individuellement (RTSP, résolution, codec, transport) — 15 min × N caméras
8. Configurer l'IA (upload modèles, ajuster seuils, tester) — 45 min
9. Créer les utilisateurs et rôles — 30 min
10. Configurer les notifications, tester chaque canal — 30 min
11. Vérifier que tout marche — 30 min

**Total** : 4 à 8 heures selon la taille du site. Chaque étape est une occasion de se tromper, d'oublier un réglage, de laisser un flanc de sécurité ouvert.

### 6.1.2 La proposition MG-VMS

Un **assistant unique** qui prend l'utilisateur par la main de l'écran d'accueil vide jusqu'au serveur pleinement opérationnel :

- Détection **automatique** de tout ce qui peut l'être (disques, GPU, caméras ONVIF, config réseau).
- Choix par défaut **explicites et modifiables** — l'installateur peut accepter la config recommandée en un clic, ou ajuster.
- Chaque étape est **validée** avant de passer à la suivante — pas de configuration silencieusement cassée.
- Reprise possible si interrompu (crash navigateur, coupure réseau, changement d'avis).
- **Bilan final** : rapport clair de ce qui marche, ce qui ne marche pas, et quoi faire ensuite.

**Objectif chiffré** : un installateur formé configure un site standard (5 à 15 caméras, GPU NVIDIA, stockage local) en **10 à 15 minutes**.

### 6.1.3 Pour qui

Trois personas cibles (détail chapitre 3) :

- **L'installateur intégrateur** — pose du matériel chez le client, mise en service rapide, 10 sites par semaine.
- **L'artisan-électricien** — peu formé aux VMS, cherche l'automatisation maximale.
- **L'utilisateur autonome (SOHO/résidentiel)** — installe lui-même son NVR, aucune formation.

---

## 6.2 User stories

### US-6.1 — Installation initiale d'un site professionnel
*En tant qu'intégrateur, je veux configurer un serveur avec 12 caméras Hikvision en 15 minutes, pour respecter mon planning de 3 sites/jour.*

**Given** un serveur fraîchement provisionné (Ubuntu + Docker Compose MG-VMS up), aucune configuration.
**When** j'accède au serveur via https://<ip>, je vois l'écran de bienvenue de l'assistant Installateur.
**Then** en suivant les étapes proposées, en moins de 15 minutes, j'ai un système avec les 12 caméras online, IA active, enregistrement configuré, admin créé, notifications testées.

### US-6.2 — Installation résidentielle
*En tant qu'utilisateur non-technicien, je veux installer MG-VMS chez moi avec ma caméra IP acheté sur Amazon.*

**Given** un mini-PC domestique avec MG-VMS installé.
**When** j'ouvre l'interface, l'assistant m'accueille avec un langage grand public (« Bienvenue ! On va configurer votre système en quelques minutes. »).
**Then** je peux ignorer les étapes avancées (GPU, notifications tierces) et arriver à un système fonctionnel en 5-8 minutes avec les défauts.

### US-6.3 — Reprise après interruption
*En tant qu'installateur, ma tablette a coupé au milieu de la configuration.*

**Given** une session d'installation interrompue à l'étape 4/8.
**When** je reviens sur le VMS après reconnexion.
**Then** l'assistant reprend là où j'en étais, avec les étapes précédentes marquées comme validées, sans redemander ce qui a déjà été fait.

### US-6.4 — Reconfiguration a posteriori
*En tant qu'admin après 6 mois d'exploitation, je veux relancer l'assistant pour ajouter un GPU.*

**Given** un système en production, l'assistant terminé il y a 6 mois.
**When** j'accède à `Administration > Assistant de configuration` je peux relancer l'assistant.
**Then** l'assistant détecte l'existant, propose uniquement de reconfigurer les étapes concernées (GPU, IA), sans casser ce qui marche.

### US-6.5 — Bilan post-installation exploitable
*En tant qu'intégrateur, à la fin de l'installation je veux un rapport PDF à remettre au client.*

**Given** installation terminée avec succès.
**When** je clique sur « Générer le rapport d'installation ».
**Then** je reçois un PDF avec : liste caméras avec URL RTSP masquées, config storage, config IA, users créés, tests réalisés (résultats OK/KO). Signable, imprimable, archivable.

### US-6.6 — Mode expert (skip)
*En tant qu'intégrateur expérimenté, je préfère configurer manuellement.*

**Given** l'écran d'accueil de l'assistant.
**When** je clique « Mode expert : configuration manuelle ».
**Then** je vais directement dans l'interface principale, l'assistant est marqué comme « ignoré » mais reste relançable.

---

## 6.3 Parcours détaillé

L'assistant est composé de **8 étapes** obligatoires + 2 optionnelles. Chaque étape est **skippable** (sauf création admin) avec choix par défaut sûr.

```
┌───────────────────────────────────────────────────────────────┐
│                                                                │
│  Étape 0 · Accueil & langue                                    │
│    ↓                                                           │
│  Étape 1 · Création du compte administrateur ⚡ obligatoire     │
│    ↓                                                           │
│  Étape 2 · Détection & config stockage                         │
│    ↓                                                           │
│  Étape 3 · Détection & config GPU + IA                         │
│    ↓                                                           │
│  Étape 4 · Découverte ONVIF & sélection caméras                │
│    ↓                                                           │
│  Étape 5 · Configuration par caméra (batch)                    │
│    ↓                                                           │
│  Étape 6 · Notifications (SMTP, Discord, Telegram, MQTT)       │
│    ↓                                                           │
│  Étape 7 · Utilisateurs additionnels                           │
│    ↓                                                           │
│  Étape 8 · Bilan & tests de bout en bout                       │
│                                                                │
│  Optionnel : Ét. A · Site & géolocalisation                    │
│  Optionnel : Ét. B · Sauvegarde initiale                       │
│                                                                │
└───────────────────────────────────────────────────────────────┘
```

Chaque étape a :
- Un **objectif** en une phrase (affiché en haut de l'écran).
- Une **estimation de temps** restant (« environ 8 minutes »).
- Un bouton **[Continuer]** ⇒ étape suivante après validation.
- Un bouton **[Ignorer cette étape]** ⇒ suivante avec valeurs par défaut.
- Un bouton **[Retour]** ⇒ étape précédente (données conservées).
- Un lien **[Aide]** ⇒ tooltip contextuel.

---

## 6.4 Détail de chaque étape

### Étape 0 — Accueil & langue

**Objectif** : sélection de la langue de l'interface + acceptation des conditions.

**Affiché** :
- Logo MG-VMS (thème auto light/dark selon OS).
- Titre : « Bienvenue dans MG-VMS » (traduit selon langue navigateur).
- Sélecteur langue : FR (défaut), EN, ES, DE, IT, PT (v3.5+).
- Estimation totale : *« Environ 10 à 15 minutes pour configurer votre système »*.
- Checkbox obligatoire : *« J'ai lu et j'accepte la [licence](#) »*.
- Deux boutons :
  - **[Commencer l'assistant]** — principal (bleu).
  - **[Mode expert : configuration manuelle]** — secondaire (texte).

**Logique** :
- Aucune donnée persistée avant Étape 1.
- Le mode expert crée un flag `installer_wizard.skipped=true` dans `db.settings` et redirige vers `/administration`.

**data-testid** : `wizard-language-select`, `wizard-accept-license`, `wizard-start`, `wizard-expert`.

### Étape 1 — Compte administrateur ⚡

**Objectif** : créer le premier admin. **Non-skippable** — une installation sans admin n'existe pas.

**Champs** :
- Nom complet (min 2 caractères)
- Email (validé RFC 5322)
- Mot de passe (min 12 caractères, force calculée avec `zxcvbn`, score ≥ 3 requis)
- Confirmation mot de passe
- Checkbox : *« Activer l'authentification à 2 facteurs (TOTP) »* — si coché, l'étape 1b affiche le QR code.

**Validation** :
- Backend refuse la création si `db.users.count() > 0` en dehors du wizard (protection contre re-execution malveillante).
- Le mot de passe est chiffré (bcrypt) avant insertion.
- Un `refresh_token` de 30 jours est créé pour permettre à l'installateur de reprendre sans reconnexion.

**Écran suivant si 2FA activée** :
- QR code TOTP + secret texte fallback (`otpauth://...`).
- Champ « Entrer le code affiché sur votre app » (Google Authenticator, Authy, Aegis…).
- Bouton **[Valider et continuer]**.

**data-testid** : `wizard-admin-name`, `-email`, `-password`, `-password-confirm`, `-2fa-enable`, `-2fa-code`, `-continue`.

### Étape 2 — Stockage

**Objectif** : configurer le pool principal d'enregistrement vidéo.

**Détection automatique au chargement** (via `GET /api/v1/system/storage/discover`) :
- Liste des disques physiques (bloc + partitions).
- Type détecté : NVMe / SSD / HDD / USB / RAID logiciel / point de montage NAS.
- Capacité libre, capacité totale.
- État SMART si disponible.

**Écran** :

```
Stockage détecté :

┌──────────────────────────────────────────────────────────────┐
│ ● NVMe 1 TB  · /dev/nvme0n1p1  · 850 GB libres  · SMART OK   │
│ ○ HDD 4 TB   · /dev/sda1        · 3.8 TB libres · SMART OK   │
│ ○ NAS Synology · nfs://192.168.1.10/nvr · 12 TB libres        │
│ ○ Ajouter manuellement...                                      │
└──────────────────────────────────────────────────────────────┘

Recommandation MG-VMS :
  Pool principal → HDD 4 TB (grande capacité, adapté à l'enregistrement).
  Pool tampon (segments récents 24h) → NVMe 1 TB (accès rapide).

Rétention : ○ 7 jours   ● 14 jours   ○ 30 jours   ○ 60 jours   ○ Personnalisé

Politique quand disque plein :
  ● Rotation automatique (supprimer les plus vieux)
  ○ Alerter et arrêter l'enregistrement
```

**Actions techniques réalisées** :
- Création du/des pools dans `db.storage_pools` avec `{path, type, capacity_gb, retention_days, policy, priority}`.
- Formatage optionnel (uniquement si l'utilisateur coche « Formater ce disque » — case décochée par défaut, confirmation renforcée).
- Test d'écriture : création d'un fichier 100 MB + lecture + suppression, mesure IOPS (utile pour bench, chapitre 16).

**Fallback** : si aucun disque exploitable détecté, l'assistant permet de saisir manuellement un chemin (montage NAS, chemin custom). Un warning explicite est affiché : *« Le stockage sur système de fichiers réseau peut affecter les performances d'enregistrement. »*.

**Mode dégradé** : si `df` échoue ou aucun disque > 5 GB, l'étape peut être skippée avec un warning stocké dans `db.settings.installer_warnings[]` — l'enregistrement sera désactivé par défaut.

**data-testid** : `wizard-storage-disk-{index}`, `-retention-days`, `-policy`, `-continue`.

### Étape 3 — GPU & IA

**Objectif** : détecter la présence d'un GPU NVIDIA, tester CUDA, choisir les modules IA à activer.

**Détection automatique** (via `GET /api/v1/system/gpu/discover`) :
- `nvidia-smi` disponible dans le container ?
- Modèle GPU, VRAM totale, driver version.
- CUDA runtime version (via `torch.version.cuda`).
- `torch.cuda.is_available()`.
- Backend NVDEC/NVENC : test d'un pipeline `ffmpeg -c:v h264_cuvid` sur un fichier de test embarqué.

**Écran (cas GPU détecté)** :

```
✅ GPU NVIDIA détecté : RTX A2000 · 6 GB VRAM · CUDA 12.4 · driver 550.54

Test rapide :
  ● NVDEC (décodage matériel H.264 / H.265) ....... ✅ OK (150 ms)
  ● CUDA inference (PyTorch)      .................. ✅ OK
  ● NVENC (encodage) ................................ ✅ OK

Modules IA disponibles :

  ☑ Détection d'objets (YOLO)         · YOLOv11n · ~15 fps par caméra
  ☑ Lecture de plaques (ANPR)         · fast-alpr · CPU-ONNX (indépendant GPU)
  ☐ Reconnaissance faciale            · InsightFace · ~10 fps par caméra
  ☐ Détection fumée                    · SmokeNet · Beta v3.0
  ☐ Détection feu                      · FireNet · Beta v3.0
  ☐ Équipements de sécurité (PPE)      · Beta v3.0
  ☐ Comptage personnes/véhicules       · v3.1
  ☐ Loitering (attente prolongée)      · v3.1
  ☐ Franchissement de ligne            · v3.0
  ☐ Zone d'intérêt                     · v3.0
  ☐ Détection animaux                   · v3.1

Modules cochés → activés par défaut sur toutes les caméras (modifiable par caméra).
```

**Écran (cas pas de GPU)** :

```
⚠ Aucun GPU NVIDIA détecté.

Les modules IA fonctionneront en CPU :
  • YOLO tournera à ~3 fps par caméra (au lieu de 15 fps).
  • ANPR fonctionne nativement en CPU (aucun impact).

Recommandation : limiter à 5 caméras avec IA active simultanément
sur ce serveur, ou installer un GPU NVIDIA (guide : [Configuration GPU](#)).

Continuer sans GPU ? [Oui, tester en CPU] [Non, je vais installer un GPU]
```

**Actions techniques** :
- Enregistre `db.settings.ai_config` avec `{device: "cuda"|"cpu", modules_enabled: [...], confidence: 0.35, interval_seconds: 2}`.
- Force `MGVMS_AI_FORCE_CPU=0` (respect du choix utilisateur).
- Pré-télécharge les modèles cochés en tâche de fond (blocking uniquement les modèles < 50 MB, les gros téléchargés post-wizard avec badge « Installation IA en cours »).

**Modes dégradés** :
- GPU présent mais CUDA KO → propose CPU forcé + tag warning dans `db.settings.installer_warnings`.
- Modèles téléchargement échec → l'étape 8 (bilan) affiche l'échec + bouton [Réessayer].

**data-testid** : `wizard-gpu-test-nvdec`, `-gpu-test-cuda`, `-ia-module-{name}`, `-continue`.

### Étape 4 — Découverte ONVIF

**Objectif** : scanner le LAN pour trouver les caméras compatibles ONVIF.

**Interaction** :
- Écran initial : *« Scanner mon réseau local à la recherche de caméras. Durée : environ 8 secondes. »* + bouton **[Lancer le scan]**.
- Pendant le scan : loader + liste qui se remplit progressivement.
- Timeout dur : 15 s.

**Résultat** :

```
6 caméras détectées :

☑ Hikvision DS-2CD2043G0-I   · 192.168.1.42  · profile_1 : 1920×1080@25fps H.264
☑ Hikvision DS-2CD2043G0-I   · 192.168.1.43  · profile_1 : 1920×1080@25fps H.264
☑ Dahua IPC-HDW3549H          · 192.168.1.44  · profile_0 : 2688×1520@15fps H.265
☑ Uniview IPC322              · 192.168.1.45  · profile_1 : 1920×1080@25fps H.264
☐ Axis P1425-E                · 192.168.1.46  · authentification requise
☐ Caméra ONVIF inconnue       · 192.168.1.47  · pas de flux principal détecté

[+ Ajouter une caméra manuellement (URL RTSP)]

Credentials par défaut à essayer (recommandé pour caméras multiples) :
  Utilisateur : admin       Mot de passe : ••••••••
```

**Actions** :
- Test ONVIF `GetDeviceInformation` + `GetProfiles` + `GetStreamUri` sur chaque IP découverte (parallèle, timeout 8s par caméra).
- Si des credentials par défaut sont fournis, retente avec pour les caméras marquées « authentification requise ».
- Les caméras cochées passent à l'étape 5.

**Skip** — si zéro caméra détectée ou si l'installateur veut configurer manuellement, il passe à l'écran manuel (identique à `/cameras > + Ajouter une caméra`).

**data-testid** : `wizard-onvif-scan`, `-camera-{ip}`, `-default-creds-user`, `-default-creds-pass`, `-continue`.

### Étape 5 — Configuration par caméra (batch)

**Objectif** : configurer les paramètres des caméras sélectionnées sans avoir à ouvrir chaque caméra individuellement.

**Écran** — tableau éditable :

```
┌────┬─────────────────────┬──────────────┬───────┬───────┬─────────┬────────┬───────┐
│ ✓  │ Nom (éditable)      │ IP           │ HD    │ SD    │ Codec   │ IA     │ REC   │
├────┼─────────────────────┼──────────────┼───────┼───────┼─────────┼────────┼───────┤
│ ✓  │ Entrée principale   │ 192.168.1.42 │ P1 ▼  │ P2 ▼  │ H.264  │ YOLO ▼ │  ☑    │
│ ✓  │ Parking             │ 192.168.1.43 │ P1 ▼  │ P2 ▼  │ H.264  │ YOLO+  │  ☑    │
│ ✓  │ Réception           │ 192.168.1.44 │ P0 ▼  │ P1 ▼  │ H.265  │ YOLO   │  ☑    │
│ ✓  │ Couloir             │ 192.168.1.45 │ P1 ▼  │ P2 ▼  │ H.264  │ ✗      │  ☑    │
└────┴─────────────────────┴──────────────┴───────┴───────┴─────────┴────────┴───────┘

Actions groupées :  [Renommer par site]  [Activer/Désactiver IA]  [Activer/Désactiver REC]

Transport RTSP :  ● TCP (recommandé, +stable)   ○ UDP (+faible latence)
```

**Détails de chaque colonne** :
- **Nom** — proposé automatiquement à partir de `ONVIF GetDeviceInformation.Manufacturer + Model` + IP, l'installateur renomme rapidement (« Entrée », « Parking »…).
- **HD / SD** — sélecteur du profil ONVIF utilisé pour flux principal (HD, enregistrement + WebRTC HD) et secondaire (SD, IA + vignettes).
- **IA** — dropdown : ✗ Aucune / YOLO / YOLO+ANPR / YOLO+Face / Custom…
- **REC** — checkbox : enregistrement continu activé ou non.

**Actions au [Continuer]** :
- Pour chaque caméra cochée : `POST /api/v1/cameras` avec les paramètres.
- Provisionnement `PUT /api/streams` vers go2rtc.
- Test de connexion RTSP `ffprobe` en parallèle (timeout 12s).
- Le passage à l'étape suivante s'affiche uniquement quand toutes les caméras sont validées ou en échec (résultat affiché sous chaque ligne).

**Mode dégradé** — si une caméra échoue au test, l'installateur peut :
- [Réessayer]
- [Modifier les credentials]
- [Ignorer cette caméra] — passe à `status: offline`, exclue de la suite du wizard.
- [Retirer complètement]

**data-testid** : `wizard-camera-row-{ip}`, `-camera-name-{ip}`, `-camera-hd-{ip}`, `-camera-ia-{ip}`, `-camera-rec-{ip}`, `-continue`.

### Étape 6 — Notifications

**Objectif** : configurer au moins un canal de notification pour les alertes critiques.

**Écran** — accordéon avec un canal par section :

```
📧 Email (SMTP)             [○ Non configuré]  →  [Configurer]
🔴 Discord (Webhook)        [○ Non configuré]  →  [Configurer]
🔵 Telegram (Bot)           [○ Non configuré]  →  [Configurer]
📱 MQTT (broker externe)    [○ Non configuré]  →  [Configurer]
🔗 Webhook générique        [○ Non configuré]  →  [Configurer]  [v3.1]
```

**Pour chaque canal cliqué** : formulaire dédié + bouton **[Tester]** qui envoie une notification de test *« Test MG-VMS installation »*. Résultat OK/KO affiché en direct.

**Mode dégradé** — l'étape est skippable. Si aucun canal n'est configuré, un warning est affiché en Étape 8 : *« Aucun canal de notification configuré. Les alertes seront visibles uniquement dans l'interface web. »*.

**data-testid** : `wizard-notif-{channel}-configure`, `-test`, `-continue`.

### Étape 7 — Utilisateurs additionnels

**Objectif** : créer les comptes des opérateurs qui utiliseront le VMS.

**Écran** — table éditable style Airtable :

```
┌────────────────────┬──────────────────────┬────────────┬────────────┬─────────┐
│ Nom                │ Email                │ Rôle       │ Sites      │ 2FA     │
├────────────────────┼──────────────────────┼────────────┼────────────┼─────────┤
│ Jean Dupont        │ jean@example.com     │ Opérateur ▼│ Tous     ▼ │  ☐      │
│ [+ Ajouter]                                                                    │
└────────────────────┴──────────────────────┴────────────┴────────────┴─────────┘

Rôles disponibles (résumé) :
  • Opérateur : voir live, alertes, exports · pas d'admin
  • Technicien : Opérateur + diagnostics + config caméras
  • Admin : tous droits
```

**Actions** :
- À la validation : `POST /api/v1/users` par ligne remplie. Mot de passe temporaire généré (16 caractères), envoyé par email si SMTP configuré (Étape 6), sinon copié dans le presse-papier + affiché à l'écran + demande de changement au premier login.

**data-testid** : `wizard-user-row-{index}`, `-user-name-{i}`, `-user-email-{i}`, `-user-role-{i}`, `-continue`.

### Étape 8 — Bilan & tests

**Objectif** : montrer le résultat de l'installation, permettre les tests de bout en bout.

**Écran** :

```
🎉 Installation quasi terminée !

Résumé :
  ✅ Compte admin créé : admin@example.com
  ✅ Stockage : 2 pools, 4.8 TB total, rétention 14 j, rotation auto
  ✅ GPU : RTX A2000 · CUDA OK · 2 modules IA activés (YOLO, ANPR)
  ✅ 12 caméras online
  ⚠ 1 caméra en échec : Axis P1425-E (192.168.1.46) — auth refusée [Diagnostic]
  ✅ Notifications : SMTP + Discord configurés (tests OK)
  ✅ 3 utilisateurs créés (Jean, Marie, Paul) — mots de passe envoyés par email

Tests de bout en bout à réaliser :

  [Lancer un test WebRTC live]   →  ○ En attente...
  [Générer une alerte de test]    →  ○ En attente...
  [Vérifier l'enregistrement]     →  ○ En attente...
  [Vérifier une détection IA]     →  ○ En attente...

Actions post-installation :

  [Télécharger le rapport PDF]
  [Terminer et aller à l'accueil]
  [Ajouter d'autres caméras]
```

**Actions techniques finales** :
- Marquer `db.settings.installer_wizard.completed_at = now()`.
- Générer le rapport PDF (voir §6.5).
- Basculer l'interface principale sur `/`.

**data-testid** : `wizard-summary`, `-test-webrtc`, `-test-alert`, `-test-rec`, `-test-ia`, `-finish`.

### Étape optionnelle A — Site & géolocalisation

**Objectif** : nommer le site, saisir l'adresse, choisir le fuseau horaire, uploader un plan.

Utile pour multi-site v3.1+. En v3.0, un seul site = « Site principal ». Skippable.

### Étape optionnelle B — Sauvegarde initiale

**Objectif** : configurer une sauvegarde automatique de la config.

- Fréquence (quotidien à 03:00 par défaut).
- Destination (pool storage local ou NAS distant).
- Rétention 30 jours.
- Chiffrement AES-256 avec passphrase (à ne pas perdre).

---

## 6.5 Rapport d'installation PDF

Généré à la fin de l'Étape 8 via `POST /api/v1/installer/report`. Format PDF signable, imprimable.

**Contenu** :
- Page 1 — En-tête : logo MG-VMS + logo client (si uploadé) + date + nom du site + nom installateur.
- Page 2 — Résumé exécutif : nombre caméras, IA activée, stockage total, rétention, admin créé.
- Page 3-5 — Détail caméras : nom, IP, résolution, codec, IA active, transport, statut.
- Page 6 — Config IA : modules actifs, seuils, calendriers d'armement.
- Page 7 — Config stockage : pools, capacités, rétention, politique.
- Page 8 — Utilisateurs : liste des comptes créés (sans mots de passe).
- Page 9 — Tests de bout en bout : résultats OK/KO.
- Page 10 — Warnings et recommandations : caméras en échec, améliorations suggérées, config GPU si absent.
- Dernière page — Bloc signature : *« L'installateur soussigné certifie… »* + case client + cachet.

Le rapport est stocké dans `db.installation_reports` pour consultation ultérieure via `/administration > Rapports`.

---

## 6.6 Reprise interrompue

Chaque validation d'étape écrit un checkpoint dans `db.settings.installer_wizard` :
```json
{
  "started_at": "2026-07-24T10:00:00+00:00",
  "current_step": 5,
  "completed_steps": [0, 1, 2, 3, 4],
  "session_token_hash": "sha256_of_installer_refresh_token",
  "data": {
    "admin_created": true,
    "storage_pools_created": ["pool_1", "pool_2"],
    "gpu_config": {...},
    "cameras_pending_configuration": [...]
  }
}
```

Au chargement de `/` :
- Si `installer_wizard.completed_at` existe → interface normale.
- Si `installer_wizard.skipped=true` → interface normale.
- Si `installer_wizard.current_step` existe → reprise à cette étape avec les données restaurées.
- Sinon → Étape 0.

Un installateur peut réinitialiser volontairement via `DELETE /api/v1/installer/state` (admin uniquement, confirmation renforcée).

---

## 6.7 Modes dégradés systémiques

| Cas | Comportement wizard |
|---|---|
| Pas de disque exploitable | Étape 2 : warning + skip permis, `record_enabled=false` par défaut caméras |
| Pas de GPU | Étape 3 : bascule CPU, YOLO à 3 fps signalé, ANPR reste OK |
| Aucune caméra ONVIF détectée | Étape 4 : bouton « Ajouter manuellement » + guide |
| Une caméra en échec | Étape 5 : ligne rouge + [Réessayer] [Ignorer] [Retirer] |
| SMTP test échec | Étape 6 : erreur explicite (« port bloqué », « auth refusée ») + [Réessayer] |
| Backup destination inaccessible | Étape B : warning + option skip |
| Coupure réseau pendant l'étape 5 | L'appel POST timeout, ligne caméra en état « Timeout — retenter » |
| Session token expire | Refresh automatique en tâche de fond, transparent |

---

## 6.8 API & modèle de données

### 6.8.1 Endpoints REST (préfixe `/api/v1/installer`)

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/installer/state` | public si aucun admin, sinon auth | État courant du wizard (étape, données) |
| POST | `/installer/step/{n}/validate` | wizard-session | Valide une étape avec ses données |
| POST | `/installer/step/{n}/skip` | wizard-session | Skip une étape (avec warnings enregistrés) |
| POST | `/installer/report` | admin | Génère le rapport PDF |
| DELETE | `/installer/state` | admin | Réinitialise le wizard |
| GET | `/system/storage/discover` | wizard-session ou admin | Détection disques |
| GET | `/system/gpu/discover` | idem | Détection GPU |
| POST | `/cameras/discover` | idem | Découverte ONVIF (déjà existant) |

**Auth spéciale wizard** : avant création du premier admin, le backend accepte les appels avec un token temporaire généré au premier accès de la page d'accueil. Ce token est stocké en cookie httpOnly + refresh via `POST /installer/session`. Après création de l'admin (Étape 1), le token est **remplacé** par un vrai JWT admin.

### 6.8.2 Schéma `db.settings.installer_wizard`

```json
{
  "started_at": "ISO datetime",
  "completed_at": "ISO datetime | null",
  "skipped": false,
  "current_step": 5,
  "completed_steps": [0, 1, 2, 3, 4],
  "installer_warnings": [
    {"step": 3, "code": "gpu_absent", "message": "..."}
  ],
  "session_token_hash": "sha256",
  "data": {
    "admin_id": "uuid",
    "storage_pool_ids": ["uuid", "uuid"],
    "gpu_config": {"device": "cuda", "cuda_version": "12.4"},
    "camera_ids_created": ["uuid", ...],
    "camera_ids_failed": [{"ip": "...", "reason": "..."}],
    "notifications_configured": ["smtp", "discord"],
    "user_ids_created": ["uuid", "uuid"]
  }
}
```

Une seule instance de ce document existe (`_id: "installer_wizard"`). Réinitialisation = suppression.

---

## 6.9 Tests d'acceptation

### TA-6.1 — Parcours complet nominal (Given/When/Then)

**Given** un serveur Docker Compose fraîchement démarré, aucune donnée en base.
**When** je charge `https://<host>/`.
**Then** l'écran Étape 0 s'affiche en français.

**Given** j'ai validé les étapes 0 à 8 avec les données minimales (5 caméras ONVIF simulées).
**When** l'étape 8 termine.
**Then** :
- `db.users` contient 1 admin actif.
- `db.storage_pools` contient au moins 1 pool.
- `db.cameras` contient les 5 caméras avec `status=online`.
- `db.settings.installer_wizard.completed_at` est renseigné.
- Une redirection vers `/` (Home) est effectuée.

### TA-6.2 — Reprise après interruption

**Given** j'ai validé les étapes 0-3, puis fermé le navigateur.
**When** je rouvre `/` (même appareil, même session).
**Then** l'assistant reprend à l'étape 4 avec les données précédentes intactes.

### TA-6.3 — Mode expert

**Given** j'accède à `/` la première fois.
**When** je clique « Mode expert : configuration manuelle ».
**Then** :
- `db.settings.installer_wizard.skipped=true`.
- Je suis redirigé vers `/administration`.
- Aucune caméra, aucun pool, aucun user en base.

### TA-6.4 — Reconfiguration a posteriori

**Given** un système en production, wizard terminé il y a 6 mois.
**When** j'accède à `Administration > Assistant de configuration > Relancer`.
**Then** un wizard s'ouvre en « mode reconfiguration » avec un badge « Reconfiguration » et propose de changer stockage/GPU/notifications sans casser l'existant.

### TA-6.5 — Bilan avec caméra en échec

**Given** j'ai configuré 5 caméras dont une échoue au test connectivité.
**When** l'étape 8 se charge.
**Then** :
- 4 caméras affichées en vert « online ».
- 1 caméra en jaune « échec » avec lien [Diagnostic].
- Un warning explicite dans le résumé.
- Le rapport PDF liste cette caméra en section « Warnings ».

### TA-6.6 — Sécurité : re-exécution non autorisée

**Given** le wizard a été complété.
**When** un attaquant envoie `POST /api/v1/installer/step/1/validate` avec un `email` différent.
**Then** HTTP 403 `installer_already_completed`. Aucune modification de base.

### TA-6.7 — Aucun admin, un seul essai

**Given** aucun admin en base.
**When** je fais `POST /api/v1/installer/step/1/validate` deux fois de suite (double-clic).
**Then** le premier appel crée l'admin. Le second retourne HTTP 409 `admin_already_exists`. Aucun doublon.

---

## 6.10 Métriques de succès

Ces métriques quantifient l'atteinte de l'objectif du chapitre (10-15 min).

**Métriques produit** :
- Durée médiane du wizard (de l'Étape 0 au clic « Terminer ») : cible ≤ 12 min pour un site 5-15 caméras standard.
- Taux de complétion (wizard terminé / wizard commencé) : cible ≥ 90%.
- Taux d'abandon à chaque étape : cible ≤ 5% par étape.
- Nombre de retours à une étape précédente : cible médiane ≤ 2.

**Métriques qualitatives** (enquête post-installation) :
- « Recommanderiez-vous MG-VMS à un pair ? » (NPS) : cible ≥ 60.
- « Combien d'appels support post-installation ? » : cible médiane 0.

**Métriques techniques** :
- Temps du scan ONVIF : P95 ≤ 15 s.
- Temps du test GPU CUDA : P95 ≤ 5 s.
- Temps de génération du rapport PDF : P95 ≤ 8 s.

---

## 6.11 Écarts avec la v2.22.0

- 🔴 **Wizard entier** — inexistant en v2.22.0. À développer intégralement pour v3.0.
- ✅ **Découverte ONVIF** — fonction backend existe (`POST /cameras/discover`), à réutiliser dans l'Étape 4.
- ✅ **Création admin** — fonction existe, à intégrer dans l'Étape 1.
- ⚠ **Détection storage** — endpoint `/system/storage` existe partiellement, à enrichir pour l'Étape 2.
- ⚠ **Détection GPU** — endpoint `/system/gpu` existe, à enrichir avec test CUDA/NVDEC.
- 🔴 **Génération PDF** — inexistant, à développer avec `reportlab` ou `weasyprint`.

Le chapitre `26-roadmap.md` planifie ce chantier comme un des livrables prioritaires v3.0.

---

## 6.12 ADR spécifiques

### ADR-12 — Wizard implémenté côté frontend, orchestration légère backend

**Contexte** : deux approches possibles — wizard-as-state-machine côté backend, ou wizard-comme-parcours-UI côté frontend.
**Décision** : le frontend gère la logique de parcours (étapes, navigation, données temporaires). Le backend fournit des endpoints atomiques (`/installer/step/{n}/validate`) qui vérifient l'ordre et persistent. `db.settings.installer_wizard` sert de checkpoint pour reprise.
**Conséquences** : frontend riche mais autonome. Backend simple. Reprise transparente si onglet perdu.
**Alternatives rejetées** : full-backend state machine (verbose, chaque changement d'étape = round-trip), full-frontend sans persistence (perte à la coupure réseau).

### ADR-13 — Token de session wizard avant premier admin

**Contexte** : les endpoints `/installer/*` sont appelés avant l'existence d'un admin, donc sans JWT.
**Décision** : à l'accès à `/` sans admin en base, le backend émet un token de session installateur en cookie httpOnly (courte durée 1 h, refresh auto). Ce token accepté uniquement sur `/installer/*` et `/system/*/discover`. Après création de l'admin (Étape 1), le token est remplacé par un vrai JWT admin.
**Conséquences** : aucune faille d'ouverture. Un serveur avec admin existant refuse l'émission du token installateur (retour 403).
**Alternatives rejetées** : basic auth avec credentials par défaut publiés (mauvaise pratique), pas d'auth (n'importe qui sur le LAN peut créer l'admin).

### ADR-14 — Rapport PDF via `weasyprint` (HTML→PDF)

**Contexte** : plusieurs approches pour générer un PDF.
**Décision** : `weasyprint` (HTML/CSS → PDF). Permet de réutiliser des templates de composants React côté serveur, styling CSS moderne, tables complexes natives.
**Conséquences** : ~ 80 MB de deps supplémentaires côté backend. Templates HTML séparés dans `templates/installer_report.html`.
**Alternatives rejetées** : `reportlab` (API bas-niveau, verbose), `pdfkit` (dépendance wkhtmltopdf CLI, obsolète).

---

## Annexes

### A. Wireframe complet (référence)

Livré en annexe séparée `annexes/wireframes/06-wizard/` (à produire par design_agent — voir Roadmap chapitre 26).

### B. Traduction i18n

Chaque texte de l'assistant est stocké dans les fichiers de traduction `/app/frontend/src/i18n/{fr,en,es,de,it,pt}/installer.json`. Clés stables (`wizard.step2.title` etc.).

### C. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : 8 étapes + 2 optionnelles · 6 user stories · 7 tests d'acceptation · 3 ADR (12-14) · reprise interrompue · rapport PDF |
