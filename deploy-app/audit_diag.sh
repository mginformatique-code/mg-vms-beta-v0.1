#!/usr/bin/env bash
# Audit diagnostic — lecture seule, aucune écriture.
# Vérifie l'état réel du déploiement (git local vs origin, code réellement
# présent dans le conteneur en cours d'exécution vs le repo) et l'état de
# quelques caméras de test (plugins, enregistrement) pour trancher entre
# "pas encore redéployé" et "le fix ne marche pas en réalité".
#
# Usage : depuis /opt/mg-vms-beta-v0.1/deploy-app : bash audit_diag.sh
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy-app"
cd "$REPO_ROOT" || { echo "repo introuvable"; exit 1; }

echo "══════════════════════════════════════════════════"
echo "1) ÉTAT GIT — local vs origin"
echo "══════════════════════════════════════════════════"
git fetch origin fix/p0-video-go2rtc-mjpeg --quiet 2>&1
echo "-- HEAD local --"; git log -1 --format='%H %ci %s'
echo "-- HEAD origin/fix/p0-video-go2rtc-mjpeg --"; git log -1 origin/fix/p0-video-go2rtc-mjpeg --format='%H %ci %s'
echo "-- git status --"; git status --short
echo

echo "══════════════════════════════════════════════════"
echo "2) IMAGE/CONTENEUR — build/démarrage"
echo "══════════════════════════════════════════════════"
docker images mgvms-backend --format 'image {{.ID}}  créée {{.CreatedSince}}  ({{.CreatedAt}})'
docker inspect mgvms-backend --format 'conteneur démarré : {{.State.StartedAt}}' 2>&1
echo

echo "══════════════════════════════════════════════════"
echo "3) CODE RÉEL DANS LE CONTENEUR"
echo "══════════════════════════════════════════════════"
docker exec mgvms-backend sh -c 'grep -n "loaded_names\|_plugin_loader" /app/pipeline_v2/downstream.py' 2>&1
echo "-- si rien au-dessus : fix v3.1.6 (plugins_used) absent du conteneur --"
docker exec mgvms-backend sh -c 'grep -n "rtsp_source = f\"ffmpeg" /app/streaming.py' 2>&1
echo "-- si rien au-dessus : fix transport TCP absent du conteneur --"
docker exec mgvms-backend sh -c 'ls /app/data/plugins/ | grep -i marketplace' 2>&1
echo "-- si une ligne au-dessus : marketplace-test existe ENCORE sur disque dans le conteneur --"
echo

echo "══════════════════════════════════════════════════"
echo "4) MONGO — enabled_plugins réel pour test / test2"
echo "══════════════════════════════════════════════════"
docker exec mgvms-mongo mongosh mgvms --quiet --eval '
db.cameras.find({name: {$in: ["test","test2"]}}, {_id:0, id:1, name:1, enabled_plugins:1}).forEach(printjson)
'
echo

echo "══════════════════════════════════════════════════"
echo "5) PLUGINS chargés au dernier démarrage backend"
echo "══════════════════════════════════════════════════"
docker logs mgvms-backend 2>&1 | grep -i "plugin_loader\|plugins_dir" | tail -40
echo

echo "══════════════════════════════════════════════════"
echo "6) ENREGISTREMENT test2 — autour de 21/08/2026 10:01:38"
echo "══════════════════════════════════════════════════"
source "$DEPLOY_DIR/.env" 2>/dev/null
TEST2_ID=$(docker exec mgvms-mongo mongosh mgvms --quiet --eval 'print(db.cameras.findOne({name:"test2"}).id)')
echo "camera test2 id = ${TEST2_ID}"
CAM_DIR="${RECORDINGS_PATH}/${TEST2_ID}"
echo "-- segments autour de l'heure de l'événement --"
find "$CAM_DIR" -name "*.mp4" -newermt "2026-08-21 09:50:00" ! -newermt "2026-08-21 10:15:00" -exec ls -la {} \; 2>&1
echo "-- stderr ffmpeg (tail) --"
tail -c 3000 "$CAM_DIR/.ffmpeg-stderr.log" 2>&1
echo "-- logs recorder pour test2 --"
docker logs mgvms-backend 2>&1 | grep -iE "test2|${TEST2_ID}" | tail -80
echo

echo "══════════════════════════════════════════════════"
echo "7) TIMELINE — segments dupliqués '02:26'"
echo "══════════════════════════════════════════════════"
find "$CAM_DIR" -name "*.mp4" -newermt "2026-08-21 02:20:00" ! -newermt "2026-08-21 02:35:00" -exec ls -la --time-style=full-iso {} \; 2>&1 | sort -k6,7
echo

echo "══════════════════════════════════════════════════"
echo "8) CAMÉRA test — derniers queue.status/occupancy.zone"
echo "══════════════════════════════════════════════════"
TEST_ID=$(docker exec mgvms-mongo mongosh mgvms --quiet --eval 'print(db.cameras.findOne({name:"test"}).id)')
docker exec mgvms-mongo mongosh mgvms --quiet --eval "
db.events.find({camera_id:\"${TEST_ID}\", type:{\$in:[\"queue.status\",\"occupancy.zone\"]}}).sort({timestamp:-1}).limit(5).forEach(printjson)
"
echo "DONE"
