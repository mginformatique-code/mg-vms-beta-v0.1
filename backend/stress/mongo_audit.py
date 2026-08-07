"""v0.7.h · Wave I · Audit MongoDB — index / TTL / tailles.

Analyse la base MG-VMS et produit un rapport actionable :
  * Collections + counts + tailles disque
  * Index existants (utilisés/non utilisés)
  * TTL en place vs. attendus
  * Recommandations d'optimisation

Usage :
    cd /app/backend && python stress/mongo_audit.py
    → produit /app/memory/MONGO_AUDIT_v0.7.h.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db, client


# Collections critiques du produit MG-VMS
EXPECTED_INDEXES = {
    "cameras": {"id", "site_id", "status"},
    "events": {"timestamp", "camera_id", "type", "kind"},
    "plates": {"timestamp", "camera_id", "plate", "track_id"},
    "recordings": {"camera_id", "start_ts", "end_ts"},
    "audit_logs": {"timestamp", "actor"},
    "users": {"email"},
    "sessions": {"user_id", "created_at"},
    "tls_certificates": {"id", "active"},
}

EXPECTED_TTL = {
    # collection : (index_field, days)
    "events": ("timestamp", 90),           # rétention 90j par défaut
    "audit_logs": ("timestamp", 180),
    "sessions": ("created_at", 30),
}


async def collection_stats(name: str) -> dict:
    try:
        st = await db.command("collStats", name)
        return {
            "count": st.get("count", 0),
            "size_mb": round(st.get("size", 0) / (1024 * 1024), 2),
            "storage_mb": round(st.get("storageSize", 0) / (1024 * 1024), 2),
            "index_size_mb": round(st.get("totalIndexSize", 0) / (1024 * 1024), 2),
            "avg_obj_size": st.get("avgObjSize", 0),
        }
    except Exception as e:
        return {"error": str(e)[:120]}


async def collection_indexes(name: str) -> list:
    try:
        return [{"name": ix["name"], "keys": ix.get("key", {}),
                 "unique": ix.get("unique", False),
                 "sparse": ix.get("sparse", False),
                 "expireAfterSeconds": ix.get("expireAfterSeconds")}
                async for ix in db[name].list_indexes()]
    except Exception as e:
        return [{"error": str(e)[:120]}]


async def audit() -> dict:
    print("=" * 70)
    print(f"MG-VMS MongoDB audit · db = {db.name}")
    print("=" * 70)
    result = {"db_name": db.name, "collections": {}, "recommendations": []}
    coll_names = await db.list_collection_names()
    for name in sorted(coll_names):
        stats = await collection_stats(name)
        indexes = await collection_indexes(name)
        idx_fields = set()
        for ix in indexes:
            for k in (ix.get("keys") or {}).keys():
                idx_fields.add(k)
        result["collections"][name] = {
            "stats": stats, "indexes": indexes, "indexed_fields": sorted(idx_fields),
        }
        # Analyse indexes attendus
        if name in EXPECTED_INDEXES:
            missing = EXPECTED_INDEXES[name] - idx_fields
            for m in missing:
                result["recommendations"].append({
                    "collection": name, "type": "missing_index",
                    "field": m, "severity": "warning",
                    "advice": f"Créer un index sur `{name}.{m}` pour accélérer les requêtes filtrées.",
                })
        # TTL
        if name in EXPECTED_TTL:
            field, days = EXPECTED_TTL[name]
            has_ttl = any(ix.get("expireAfterSeconds") is not None for ix in indexes)
            if not has_ttl:
                result["recommendations"].append({
                    "collection": name, "type": "missing_ttl",
                    "field": field, "severity": "info",
                    "advice": f"Ajouter un TTL {days}j sur `{name}.{field}` pour purger automatiquement.",
                })
        # Grosses collections sans index sur timestamp
        if stats.get("count", 0) > 100_000 and "timestamp" not in idx_fields \
                and "start_ts" not in idx_fields:
            result["recommendations"].append({
                "collection": name, "type": "large_no_time_index",
                "severity": "warning",
                "advice": f"{name} contient {stats['count']} docs sans index temporel — les scans full-collection seront lents.",
            })
        # Rapport
        st = stats
        print(f"\n▸ {name:30s}  count={st.get('count','?'):>10}  "
              f"size={st.get('size_mb', '?'):>8} MB  "
              f"indexes={len(indexes)}")

    print(f"\n{'=' * 70}")
    print(f"Recommandations : {len(result['recommendations'])}")
    for r in result["recommendations"]:
        print(f"  [{r['severity']:>7}] {r['collection']}.{r.get('field','')}  → {r['advice']}")

    out = Path("/app/memory/MONGO_AUDIT_v0.7.h.json")
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f"\n✅ Rapport détaillé → {out}")
    return result


if __name__ == "__main__":
    try:
        asyncio.run(audit())
    finally:
        client.close()
