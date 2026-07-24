#!/usr/bin/env python3
"""MG-VMS — Audit de stabilité des flux caméra (RTSP externe ↔ MG-VMS ↔ go2rtc).

Ce script s'exécute sur le serveur GPU réel où vous avez des vraies caméras RTSP
externes branchées. Il :
  1. Se connecte à MG-VMS avec les credentials admin.
  2. Ouvre N consommateurs MJPEG simultanés sur une caméra donnée.
  3. Prend des snapshots du journal lifecycle à intervalles réguliers.
  4. Analyse la stabilité : compte les actions "interdites" (created/destroyed/
     registering/stream_absent_from_go2rtc) qui indiqueraient un cycle anormal.

Usage
-----
  python3 audit_stream_stability.py \\
    --url https://mg-vms.example.com \\
    --email admin@mg-vms.com \\
    --password Admin@2026 \\
    --camera-id 12ab34cd-5678-... \\
    --consumers 3 \\
    --duration 900       # 15 minutes

Verdict PASS : aucune action de churn n'a été enregistrée pendant la durée du test.
Verdict FAIL : au moins une action interdite → cycle anormal, à investiguer via le
                journal détaillé (afficher les entrées interdites avec leur `caller`
                pour identifier le composant fautif).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print("Installez httpx : pip install httpx", file=sys.stderr)
    sys.exit(2)


FORBIDDEN_ACTIONS = {
    "created",                    # register_camera_stream a fait DELETE+PUT (churn)
    "destroyed",                  # unregister_camera_stream a fait DELETE (churn)
    "registering",                # en train de faire register_camera_stream (churn)
    "register_failed",            # tentative de register qui a échoué
    "stream_absent_from_go2rtc",  # anomalie interne : le stream a disparu de go2rtc
}


async def login(client: httpx.AsyncClient, url: str, email: str, password: str) -> str:
    r = await client.post(f"{url}/api/auth/login",
                          json={"email": email, "password": password})
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"Login OK mais pas de access_token dans la réponse : {r.text[:200]}")
    return token


async def fetch_journal(client: httpx.AsyncClient, url: str, token: str, camera_id: str) -> dict:
    r = await client.get(f"{url}/api/diagnostics/stream-lifecycle/{camera_id}?limit=200",
                          headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


async def mjpeg_consumer(url: str, token: str, camera_id: str, duration: int,
                          consumer_id: int, results: list):
    """Ouvre un flux MJPEG et le tient ouvert `duration` secondes. Compte les octets."""
    started = time.monotonic()
    total_bytes = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=None)) as client:
            async with client.stream("GET", f"{url}/api/stream/{camera_id}/live.mjpeg?hd=0",
                                       headers={"Authorization": f"Bearer {token}"}) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes():
                    total_bytes += len(chunk)
                    if time.monotonic() - started >= duration:
                        break
    except Exception as e:
        results.append({"id": consumer_id, "error": f"{type(e).__name__}: {e}",
                         "bytes": total_bytes,
                         "duration": round(time.monotonic() - started, 1)})
        return
    results.append({"id": consumer_id, "error": None, "bytes": total_bytes,
                     "duration": round(time.monotonic() - started, 1)})


async def snapshot_task(client: httpx.AsyncClient, url: str, token: str, camera_id: str,
                        duration: int, snapshots: list):
    """Prend un snapshot du journal toutes les 30s pendant `duration` secondes."""
    interval = 30
    for t in range(0, duration + 1, interval):
        try:
            data = await fetch_journal(client, url, token, camera_id)
            snapshots.append({"t_offset": t, "journal": data})
            print(f"  [T=+{t:4d}s] entries={len(data['entries'])} · "
                  f"fail_count={data['consecutive_probe_failures']}")
        except Exception as e:
            print(f"  [T=+{t:4d}s] SNAPSHOT FAILED: {e}")
        if t + interval > duration:
            break
        await asyncio.sleep(interval)


def analyze(snapshots: list, camera_id: str, camera_name: str) -> dict:
    """Analyse tous les snapshots — compte les actions interdites et le delta."""
    print("\n" + "═" * 78)
    print("ANALYSE DE STABILITÉ")
    print("═" * 78)
    if not snapshots:
        return {"verdict": "ERROR", "reason": "aucun snapshot collecté"}
    # Snapshot initial vs final : delta uniquement
    initial_ts = {e["ts"] for e in snapshots[0]["journal"]["entries"]}
    final_entries = snapshots[-1]["journal"]["entries"]
    new_entries = [e for e in final_entries if e["ts"] not in initial_ts]

    counts = Counter(e["action"] for e in new_entries)
    forbidden = {a: c for a, c in counts.items() if a in FORBIDDEN_ACTIONS}
    total = sum(counts.values())

    print(f"\nCaméra : {camera_name} (id={camera_id})")
    print(f"Durée du test : {snapshots[-1]['t_offset']}s")
    print(f"Nouvelles transitions journal : {total}")
    print(f"\nActions vues (nouvelles depuis T=0) :")
    for action, c in sorted(counts.items(), key=lambda x: -x[1]):
        marker = " 🚨 FORBIDDEN" if action in FORBIDDEN_ACTIONS else "  ✅"
        print(f"  {action:32s} : {c}{marker}")

    if forbidden:
        # Extraire les entrées interdites avec détails (pour diag)
        print(f"\n🚨 CYCLE ANORMAL DÉTECTÉ — actions interdites :")
        for e in new_entries:
            if e["action"] in FORBIDDEN_ACTIONS:
                print(f"  {e['ts']} {e['action']:<26} reason={e['reason']!r} caller={e['caller']!r}")
        return {"verdict": "FAIL", "forbidden": forbidden, "total": total}
    print(f"\n✅ PASS — aucune action de churn détectée sur toute la durée du test.")
    return {"verdict": "PASS", "forbidden": {}, "total": total}


async def main():
    parser = argparse.ArgumentParser(description="Audit de stabilité MG-VMS ↔ go2rtc")
    parser.add_argument("--url", required=True, help="URL du backend (ex: https://mg-vms.example.com)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--camera-id", required=True,
                        help="ID de la caméra à auditer (visible dans /cameras)")
    parser.add_argument("--consumers", type=int, default=3,
                        help="Nombre de consommateurs MJPEG simultanés (défaut 3)")
    parser.add_argument("--duration", type=int, default=900,
                        help="Durée du test en secondes (défaut 900 = 15 min)")
    args = parser.parse_args()

    print(f"\nAUDIT DE STABILITÉ MG-VMS")
    print(f"══════════════════════════════════════════════════════════════════")
    print(f"  Backend       : {args.url}")
    print(f"  Camera ID     : {args.camera_id}")
    print(f"  Consumers     : {args.consumers}")
    print(f"  Durée         : {args.duration}s ({args.duration // 60} min)")
    print(f"  Démarrage     : {datetime.now(timezone.utc).isoformat()}")
    print(f"══════════════════════════════════════════════════════════════════\n")

    async with httpx.AsyncClient(timeout=15) as client:
        print("Login...")
        token = await login(client, args.url, args.email, args.password)
        print("Login OK\n")
        # Verify camera exists + fetch name
        r = await client.get(f"{args.url}/api/cameras/{args.camera_id}",
                              headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        cam = r.json()
        print(f"Caméra : {cam.get('name')} · status={cam.get('status')} · rtsp={cam.get('rtsp_masked','?')}\n")

        # Start consumers + snapshot task in parallel
        snapshots: list = []
        results: list = []
        tasks = [
            asyncio.create_task(snapshot_task(client, args.url, token, args.camera_id,
                                               args.duration, snapshots))
        ]
        for i in range(args.consumers):
            tasks.append(asyncio.create_task(
                mjpeg_consumer(args.url, token, args.camera_id, args.duration, i + 1, results)
            ))
        print(f"Lancement de {args.consumers} consommateurs + snapshots journal…\n")
        await asyncio.gather(*tasks)

        print("\n" + "═" * 78)
        print("RÉSULTATS CONSOMMATEURS MJPEG")
        print("═" * 78)
        for r_ in sorted(results, key=lambda x: x["id"]):
            status = "✅" if r_["error"] is None else "❌"
            print(f"  {status} Consumer #{r_['id']}: {r_['bytes']:>10} octets en {r_['duration']}s"
                  + (f"  ERR: {r_['error']}" if r_["error"] else ""))

        # Snapshot final complet pour l'analyse
        final = await fetch_journal(client, args.url, token, args.camera_id)
        snapshots.append({"t_offset": args.duration, "journal": final})

        verdict = analyze(snapshots, args.camera_id, cam.get("name", "?"))
        # Sauvegarde du journal complet en fichier pour analyse humaine
        out_path = f"/tmp/audit_{args.camera_id}_{int(time.time())}.json"
        with open(out_path, "w") as f:
            json.dump({"snapshots": snapshots, "consumer_results": results,
                        "verdict": verdict}, f, indent=2, default=str)
        print(f"\nJournal complet sauvegardé : {out_path}")
        sys.exit(0 if verdict["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    asyncio.run(main())
