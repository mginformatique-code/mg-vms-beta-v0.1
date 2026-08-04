"""MG-VMS · WSDL path helper.

**Objectif** : rendre les initialisations ``ONVIFCamera`` autonomes du package
Python ``onvif-zeep-async``, dont les distributions PyPI récentes ne bundlent
plus les fichiers WSDL (voir /root/.venv/lib/python3.11/site-packages/onvif/
qui ne contient AUCUN dossier ``wsdl``).

**Solution** : embarquer directement les WSDL dans ``backend/wsdl/`` (versionnés
dans git) et forcer tous les ``ONVIFCamera(...)`` du projet à utiliser ce
répertoire via ``wsdl_dir=WSDL_DIR``.

Bénéfices :
  - Installation Docker/prod immédiate, sans dépendance à Internet ni au
    package Python.
  - Version des WSDL alignée sur celle testée en dev (reproductibilité).
  - Découverte ONVIF opérationnelle out-of-the-box.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("wsdl")

# Répertoire cible : /app/backend/wsdl (via env override ``MGVMS_WSDL_DIR``
# pour les déploiements exotiques Docker/Vercel/Railway).
WSDL_DIR: str = os.environ.get(
    "MGVMS_WSDL_DIR",
    str(Path(__file__).resolve().parent / "wsdl"),
)

# Fichiers WSDL requis au démarrage (les 7 essentiels VMS).
REQUIRED_WSDL: tuple[str, ...] = (
    "devicemgmt.wsdl",
    "media.wsdl",
    "media2.wsdl",
    "ptz.wsdl",
    "events.wsdl",
    "imaging.wsdl",
    "deviceio.wsdl",
)

# Fichiers optionnels (ONVIF avancé — access control, thermal, etc.). Absents
# sur certains mirrors mais non-bloquants pour une VMS classique.
OPTIONAL_WSDL: tuple[str, ...] = (
    "analytics.wsdl", "recording.wsdl", "replay.wsdl", "search.wsdl",
    "receiver.wsdl", "display.wsdl", "remotediscovery.wsdl",
    "accesscontrol.wsdl", "doorcontrol.wsdl", "advancedsecurity.wsdl",
    "onvif.xsd", "types.xsd", "t-1.xsd", "b-2.xsd", "bf-2.xsd", "ws-addr.xsd",
)


def validate_wsdl_dir() -> dict:
    """Valide la présence des WSDL au démarrage du backend.

    Retourne un dict ``{"ok": bool, "missing": [...], "found": N, "path": ...}``.
    Log un warning explicite si un WSDL essentiel manque — sans crasher le
    backend (les endpoints ONVIF échoueront gracieusement).
    """
    path = Path(WSDL_DIR)
    result = {
        "ok": True,
        "path": str(path),
        "found": 0,
        "missing_required": [],
        "missing_optional": [],
    }
    if not path.is_dir():
        result["ok"] = False
        result["missing_required"] = list(REQUIRED_WSDL)
        logger.error(
            "WSDL · répertoire ABSENT : %s. La découverte ONVIF sera indisponible. "
            "Vérifiez la copie du dossier backend/wsdl/ dans l'image Docker.",
            path,
        )
        return result

    for f in REQUIRED_WSDL:
        if (path / f).is_file():
            result["found"] += 1
        else:
            result["ok"] = False
            result["missing_required"].append(f)
    for f in OPTIONAL_WSDL:
        if not (path / f).is_file():
            result["missing_optional"].append(f)

    if result["ok"]:
        logger.info(
            "WSDL · %d/%d essentiels + %d/%d optionnels présents dans %s",
            result["found"], len(REQUIRED_WSDL),
            len(OPTIONAL_WSDL) - len(result["missing_optional"]),
            len(OPTIONAL_WSDL), path,
        )
    else:
        logger.error(
            "WSDL · %d essentiel(s) MANQUANT(S) : %s. Certains endpoints ONVIF "
            "(PTZ, Media2, découverte) échoueront tant que ces fichiers ne sont "
            "pas dans %s",
            len(result["missing_required"]), result["missing_required"], path,
        )
    return result


def onvif_camera(ip: str, port: int, user: str, password: str, **kw):
    """Factory ``ONVIFCamera`` centralisée : injecte automatiquement
    ``wsdl_dir=WSDL_DIR`` pour toutes les instanciations du projet.

    Utilisez cette fonction plutôt que d'appeler ``ONVIFCamera(...)``
    directement afin de garantir la portabilité (dev/Docker/prod).

    v0.4 · Messages d'erreur clairs : si un fichier WSDL essentiel est
    manquant, remonte une ``FileNotFoundError`` explicite plutôt que le
    message générique "identifiants incorrects" (source de confusion pour
    les utilisateurs quand le vrai problème est le bundle WSDL).
    """
    from onvif import ONVIFCamera  # local import (charge zeep tardivement)
    # Pre-flight check : vérifie que le fichier devicemgmt.wsdl est là AVANT
    # d'essayer la connexion réseau. Sinon zeep lève des erreurs opaques que
    # les callers interprètent (à tort) comme des erreurs d'authentification.
    from pathlib import Path as _P
    if not (_P(WSDL_DIR) / "devicemgmt.wsdl").is_file():
        raise FileNotFoundError(
            f"WSDL ONVIF manquants dans {WSDL_DIR}. "
            f"L'erreur suivante n'est PAS un problème d'identifiants — "
            f"le dossier backend/wsdl/ n'a pas été correctement embarqué dans "
            f"l'image. Vérifiez `docker compose build` ou définissez "
            f"MGVMS_WSDL_DIR=<chemin> vers un bundle WSDL valide."
        )
    try:
        return ONVIFCamera(ip, port, user, password, wsdl_dir=WSDL_DIR, **kw)
    except FileNotFoundError as e:
        # Attrape aussi les XSD manquants (b-2, xmlmime, envelope, etc.)
        raise FileNotFoundError(
            f"WSDL/XSD ONVIF partiellement manquants dans {WSDL_DIR} : {e}. "
            f"Ce n'est PAS un problème d'identifiants. Reconstruisez l'image "
            f"Docker pour restaurer le bundle WSDL complet."
        ) from e
