"""MG-VMS · Pipeline v2 — Architecture UNIQUE (v0.4.3, Feb 2026).

Un seul chemin d'exécution IA dans le backend :

    ai_engine.ai_loop
        → PipelineRuntime.worker(camera_id)
            → CameraWorker.analyze(ndarray | bytes, enabled_plugins, camera)
                → FrameContext (image partagée, ROIs partagés, JPEG memoizés)
                → stages : decode → motion → yolo → tracking → roi → anpr
        → run_downstream(cam, ctx, result)
            → plugin_bus.dispatch_pipeline(precomputed_detections, tracks)
            → scenarios / smart_zones / persistance plaques

**Règle absolue** (v0.4.3) : le CameraWorker est l'unique autorité qui
décide quels plugins reçoivent une frame. Aucun plugin ne s'auto-déclenche.
``enabled_plugins`` vide/null/absent ⇒ zéro plugin, zéro CPU, zéro GPU
(fermeture stricte, fail-safe).

Modules :
    - ``frame_context`` : dataclass unique partagée (image, ROIs, cache JPEG)
    - ``camera_worker`` : pipeline PAR caméra (état isolé)
    - ``tracking``      : TrackerPool — un tracker par caméra
    - ``downstream``    : dispatch aux plugins + persistance métier
    - ``registry``      : CameraGraph — précompile les étapes actives par caméra
    - ``scenarios``     : heuristiques d'alertes (intrusion, collision…)
    - ``anpr_quality``  : hystérésis qualité / caméras spécialisées
    - ``inspector``     : métriques temps par stage (UI Diagnostics)
"""
