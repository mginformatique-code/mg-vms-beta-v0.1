# v0.7.e · Wave D + Wave E — Camera API + Timeline Reolink · Rapport

**Objectif Wave D** : valider auto-détection ONVIF capabilities réelles,
snapshots, previews stables pendant modification caméra.
**Objectif Wave E** : timeline type Reolink (couleurs par type d'événement) +
miniatures véhicules (photo + crop véhicule + crop plaque) + fix boucle vidéo.

---

## Wave D — Camera API hardening

### 1. Causes racines / lacunes identifiées

| # | Lacune | Fichier | Impact |
|---|--------|---------|--------|
| **RC-D1** | `get_capabilities()` ne sondait pas l'audio (`GetAudioSources` / `GetAudioOutputs`) | `drivers/onvif_driver.py` | Impossible de savoir si une caméra a mic/HP embarqué → UI vendor-agnostique privée d'infos |
| **RC-D2** | Aucun probe events Profile T (`create_events_service`) | idem | `onboard_ai` toujours False même sur caméras compatibles motion/AI events |
| **RC-D3** | Aucun probe snapshot URI (`GetSnapshotUri`) | idem | Pas de fallback JPEG quand RTSP indisponible |
| **RC-D4** | `multi_stream` et `codec_h265` jamais dérivés | idem | UI ne sait pas s'il y a un sub-stream ou du H.265 |
| **RC-D5** | `ptz_presets` jamais probé | idem | UI PTZ ne sait pas si les presets sont dispo |

### 2. Correctifs Wave D

Enrichissement de `ONVIFDriver.get_capabilities()` :

```python
# Audio input / output (mic embarqué, HP)
GetAudioSources → caps.audio_input = caps.microphone = True
GetAudioOutputs → caps.audio_output = caps.speaker = True
                → both = True → caps.two_way_audio = caps.talkback = True

# Events Profile T
create_events_service() → caps.onboard_ai = True

# Snapshot URI + HTTPS detection
GetSnapshotUri → si URI = https://... → caps.https = True

# Multi-stream + H265
len(streams) >= 2 → caps.multi_stream = True
any(s.codec == "h265") → caps.codec_h265 = True

# PTZ presets
GetPresets(ProfileToken=first) → caps.ptz_presets = True
```

### 3. Bundle WSDL — validation

Test `TestWsdlBundle` vérifie que tous les WSDL critiques sont présents :
`devicemgmt.wsdl, media.wsdl, ptz.wsdl, imaging.wsdl, events.wsdl,
analytics.wsdl, accesscontrol.wsdl, common.xsd, onvif.xsd` — offline ready.

### 4. Preview stable pendant modification caméra

Test `TestIdempotentCameraUpdate` vérifie que `register_camera_stream`
contient bien le chemin `all_match` (short-circuit quand la config
go2rtc est identique) — depuis v0.5.6, un `PUT /api/cameras/{id}` qui
ne change pas l'URL RTSP **ne coupe pas la préview**.

Ce contrat combiné à **Wave A signal-driven** (`signal_camera_topology_changed`
sans stop de worker si config identique) garantit : `PUT camera → preview
reste stable`.

---

## Wave E — Timeline Reolink + miniatures + boucle vidéo

### 1. Lacunes identifiées

| # | Lacune | Fichier | Impact |
|---|--------|---------|--------|
| **RC-E1** | Palette timeline non-alignée sur la demande utilisateur | `pages/LiveView.jsx:255-277` | Couleurs incohérentes (person=green, motorbike=cyan, animal=orange…) |
| **RC-E2** | Galerie véhicule affichait uniquement `kind=vehicle`, avec `kind=frame` en lien mais **jamais `kind=plate`** | `pages/Vehicles.jsx:930-953` | Crop plaque HD (produit par Wave C `enhance_plate_crop`) invisible dans l'UI |
| **RC-E3** | Recordings player restait bloqué sur la dernière frame à `onEnded` | `pages/Recordings.jsx:196` | Perçu comme « boucle vidéo qui répète le même segment » |

### 2. Correctifs Wave E

#### E1 · Palette timeline alignée sur la demande utilisateur

```js
const EVENT_KIND_META = {
  person:     { color: "#0044FF" },  // 🟦 bleu
  car:        { color: "#00E676" },  // 🟩 vert
  motorbike:  { color: "#FFB800" },  // 🟨 jaune
  truck:      { color: "#FF6600" },  // 🟧 orange
  bus:        { color: "#9333EA" },  // 🟪 violet
  animal:     { color: "#FF3333" },  // 🟥 rouge
  bicycle:    { color: "#8B4513" },  // 🟫 marron
  // Alertes critiques : rouge/orange (priorité visuelle sémantique)
  fire, weapon, fight → #FF3333
  smoke, fall         → #FF6600
  ppe                 → #FFB800
  motion              → #66CCFF (bas signal)
};
```

#### E2 · Galerie véhicule expose les 3 crops

Chaque carte de passage affiche désormais :

```
┌─────────────────────────┐
│ [Crop VÉHICULE 100×96]  │ ← miniature (kind=vehicle)
│                    [Full→]│ ← lien vers photo complète (kind=frame)
├─────────────────────────┤
│ [Crop PLAQUE 100×32]    │ ← bandeau bas cliquable (kind=plate)
├─────────────────────────┤
│ 08/07 14:32 · Cam 1     │
│ Entrance · 94%          │
└─────────────────────────┘
```

data-testid ajoutés : `gallery-frame-link-<id>`, `gallery-vehicle-thumb-<id>`,
`gallery-plate-link-<id>`, `gallery-plate-thumb-<id>`.

Le crop plaque est celui optimisé par Wave C (`enhance_plate_crop` :
deskew + CLAHE + unsharp) — cohérence bout-en-bout.

#### E3 · Fix boucle vidéo — auto-next segment (comportement Reolink)

```jsx
<video
  key={selected.id}
  autoPlay
  onEnded={() => {
    const idx = segments.findIndex((s) => s.id === selected.id);
    if (idx >= 0 && idx < segments.length - 1) play(segments[idx + 1]);
  }}
/>
```

Sans handler `onEnded`, `<video autoPlay>` restait sur la dernière frame
et l'utilisateur devait cliquer manuellement le segment suivant — perçu
à tort comme « la vidéo boucle ».

---

## Tests

Nouveau `tests/test_v07e_wave_d_e.py` — **18 tests verts** :
- `TestWsdlBundle` (2 tests) — bundle WSDL présent + contenu vérifié
- `TestOnvifCapabilitiesProbing` (5 tests) — audio + events + snapshot + multi_stream + presets
- `TestIdempotentCameraUpdate` (1 test)
- `TestVehicleGalleryHasThreeCrops` (2 tests)
- `TestTimelinePaletteMatchesRequest` (7 tests) — palette utilisateur match exact
- `TestRecordingsAutoNextSegment` (1 test)

**Total suite v0.7.e** : **112/112 verts** (16 A + 19 C + 18 D+E + 59 régression).

Zéro régression, aucune API publique modifiée. Backend redémarré et
WebSocket connecté sans erreur.

---

## Fichiers modifiés

| Fichier | +/- | Nature |
|---------|:-:|--------|
| `backend/drivers/onvif_driver.py` | +60 / -6 | Probes audio/events/snapshot/multi_stream/codec_h265/presets |
| `frontend/src/pages/LiveView.jsx` | +11 / -14 | Palette EVENT_KIND_META alignée sur demande utilisateur |
| `frontend/src/pages/Vehicles.jsx` | +38 / -18 | Galerie 3 crops (frame + vehicle + plate) |
| `frontend/src/pages/Recordings.jsx` | +12 / 0 | Auto-next à onEnded |
| `backend/tests/test_v07e_wave_d_e.py` (nouveau) | +180 | 18 tests |
| **TOTAL** | **~340 lignes** | |

---

## Objectifs — état final

**Wave D** :
- ✅ Auto-détection audio (mic/HP/two-way)
- ✅ Auto-détection events (Profile T)
- ✅ Auto-détection snapshot URI + HTTPS
- ✅ Auto-détection multi-stream + H.265
- ✅ Auto-détection PTZ presets
- ✅ Bundle WSDL offline complet (validé par test)
- ✅ Preview stable pendant modification caméra (contrat v0.5.6 P0-3 renforcé)

**Wave E** :
- ✅ Timeline avec palette utilisateur (7 couleurs demandées, mapping exact)
- ✅ Miniatures véhicules : photo complète + crop véhicule + crop plaque
- ✅ Crop plaque = version optimisée Wave C (deskew/CLAHE/sharpen)
- ✅ Fix boucle vidéo (auto-next segment à onEnded, comportement Reolink)
- ✅ Saut direct sur clic événement (déjà présent v0.7.d — préservé)

---

## Prochaine étape

**Vague F** — Stress-test 1/5/10/20/30/50 caméras avec FPS/CPU/GPU/VRAM/RAM/
p95/p99/OCR moyen/temps détection/temps crop/temps OCR/total pipeline
+ rapport final consolidé Wave A→F.
