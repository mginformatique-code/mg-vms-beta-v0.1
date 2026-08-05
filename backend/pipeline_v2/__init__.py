"""MG-VMS · Pipeline Engine v2 — Architecture inversée (Feb 2026).

**Bascule majeure** : le **Pipeline Engine** devient le chef d'orchestre.
Le Plugin Manager ne pilote plus le traitement — il ne fait que **fournir**
les providers (detection / tracking / recognition / consumers).

Architecture cible :
    Camera → Frame Acquisition → Scheduler → Cache → Pre-processing
        → Detection → Tracking → ROI Extraction → Recognition
        → Fusion → Business Logic → Events → Notifications

Chaque étape est indépendante et branchable. Les plugins sont ultra-simples
(``providers``) — ils font UNE seule tâche et retournent un résultat
standardisé, sans se soucier du cache, de la BD, des websockets, du
tracking, ni des règles métier.

Modules du package :
    - ``interfaces``  : Protocols stables + dataclasses résultats standardisés
    - ``fusion``      : FusionEngine (6 stratégies configurables par caméra)
    - ``stages``      : PipelineStage de base + implémentations par défaut
    - ``engine``      : PipelineEngine — orchestrateur du pipeline
    - ``scheduler``   : FrameScheduler multi-caméra (FPS/priorité)
    - ``adapter``     : compat rétro (wrap les plugins existants en providers v2)
"""
