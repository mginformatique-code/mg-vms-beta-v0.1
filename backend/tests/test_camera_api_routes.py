"""Test d'intégration · route /api/camera-devices/{id}/discover.

Vérifie que la route :
    - Charge la caméra en base
    - Résout le bon provider via camera_api.registry
    - Instancie le provider avec la config API
    - Retourne un JSON aligné sur le contrat DeviceInfo/Capabilities/Network/Users
    - Persiste `manufacturer`/`model`/`api_capabilities` dans Mongo

Le provider Reolink est instancié réellement, mais son client httpx est remplacé
par un MockTransport → aucun accès réseau requis.
"""
import asyncio
import os
import uuid

import httpx
import pytest


def _fresh_db():
    import motor.motor_asyncio
    client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
    import sys
    new_db = client[os.environ["DB_NAME"]]
    for mod in ("database", "auth", "streaming", "routers"):
        m = sys.modules.get(mod)
        if m is not None and hasattr(m, "db"):
            m.db = new_db
    return new_db


def _reolink_mock_transport() -> httpx.MockTransport:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/cgi-bin/api.cgi"
        cmds = json.loads(request.read().decode())
        catalog = {
            "Login": {"Token": {"name": "tok", "leaseTime": 3600}},
            "Logout": {},
            "GetDevInfo": {"DevInfo": {"model": "RLC-81MA", "firmVer": "v3.1.0",
                                         "hardVer": "IPC", "serial": "S123",
                                         "name": "PytestCam", "channelNum": 1}},
            "GetAbility": {"Ability": {
                "hddManage": {"permit": 1, "ver": 0},
                "abilityChn": [{"ptzCtrl": {"permit": 1, "ver": 0},
                                 "supportIrMode": {"permit": 1, "ver": 0}}]}},
            "GetLocalLink": {"LocalLink": {"mac": "aa:bb:cc:dd:ee:ff",
                                             "type": "static",
                                             "static": {"ip": "192.168.1.55",
                                                        "gateway": "192.168.1.1",
                                                        "mask": "255.255.255.0"}}},
            "GetNetPort": {"NetPort": {"httpPort": 80, "httpsPort": 443,
                                         "rtspPort": 554, "onvifPort": 8000}},
            "GetUser": {"User": [{"userName": "admin", "level": 0}]},
        }
        out = []
        for c in cmds:
            cmd = c["cmd"]
            v = catalog.get(cmd, None)
            if v is None:
                out.append({"cmd": cmd, "code": 1, "error": {"detail": "unk", "rspCode": -1}})
            else:
                out.append({"cmd": cmd, "code": 0, "value": v})
        return httpx.Response(200, json=out)

    return httpx.MockTransport(handler)


def test_discover_route_returns_full_payload_and_persists(monkeypatch):
    async def run():
        db = _fresh_db()
        # Seed caméra minimale
        cam_id = f"pytest-api-{uuid.uuid4().hex[:6]}"
        site = await db.sites.find_one({}, {"_id": 0}) or {"id": "s1", "name": "S1"}
        await db.cameras.insert_one({
            "id": cam_id, "name": "pytest", "site_id": site["id"], "site_name": site["name"],
            "mode": "rtsp", "ip": "192.0.2.55", "rtsp_url": "rtsp://x/y",
            "api_host": "192.0.2.55", "api_port": 443, "api_scheme": "https",
            "api_verify_ssl": False, "api_username": "admin",
            "api_password_enc": "", "api_provider": "reolink",
        })
        # Injecte le mock transport dans le provider
        from camera_api.providers.reolink import ReolinkProvider
        original_init = ReolinkProvider.__init__

        def patched_init(self, config):
            original_init(self, config)
            self._client = httpx.AsyncClient(base_url=self.base_url,
                                              transport=_reolink_mock_transport(),
                                              verify=False, timeout=5)
            # Force le password (pas d'enc en base pour ce test)
            self.password = "s3cret"

        monkeypatch.setattr(ReolinkProvider, "__init__", patched_init)

        # Appel de la route directement
        from routes.camera_api import api_discover
        user = {"id": "u1", "email": "test@x", "role": "admin",
                "permissions": {"manage_cameras": True, "view_live": True},
                "site_ids": []}
        payload = await api_discover(cam_id, user=user)
        assert payload["provider"] == "reolink"
        assert payload["device_info"]["model"] == "RLC-81MA"
        assert payload["device_info"]["manufacturer"] == "Reolink"
        assert payload["capabilities"]["ptz"] is True
        assert payload["capabilities"]["ir"] is True
        assert payload["network"]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert payload["network"]["https_port"] == 443
        assert len(payload["users"]) == 1
        assert payload["users"][0]["role"] == "admin"

        # Persistance en Mongo
        cam = await db.cameras.find_one({"id": cam_id}, {"_id": 0})
        assert cam["manufacturer"] == "Reolink"
        assert cam["model"] == "RLC-81MA"
        assert cam["api_provider"] == "reolink"
        assert cam["api_capabilities"]["ptz"] is True
        assert cam.get("api_last_seen"), "api_last_seen doit être renseigné"

        # Cleanup
        await db.cameras.delete_one({"id": cam_id})

    asyncio.run(run())


def test_discover_route_401_on_wrong_creds(monkeypatch):
    async def run():
        db = _fresh_db()
        cam_id = f"pytest-api-badpwd-{uuid.uuid4().hex[:6]}"
        site = await db.sites.find_one({}, {"_id": 0}) or {"id": "s1", "name": "S1"}
        await db.cameras.insert_one({
            "id": cam_id, "name": "pytest", "site_id": site["id"], "site_name": site["name"],
            "api_host": "192.0.2.55", "api_scheme": "https", "api_port": 443,
            "api_username": "admin", "api_provider": "reolink",
        })

        def fail_transport(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"cmd": "Login", "code": 1,
                                                "error": {"detail": "login failed",
                                                          "rspCode": -7,
                                                          "auth_warning_info": {
                                                              "remain_times": 8,
                                                              "unlock_time": 0}}}])

        from camera_api.providers.reolink import ReolinkProvider
        original = ReolinkProvider.__init__

        def patched(self, config):
            original(self, config)
            self._client = httpx.AsyncClient(base_url=self.base_url,
                                              transport=httpx.MockTransport(fail_transport),
                                              verify=False, timeout=5)
            self.password = "wrong"

        monkeypatch.setattr(ReolinkProvider, "__init__", patched)

        from fastapi import HTTPException
        from routes.camera_api import api_discover
        user = {"id": "u1", "email": "test@x", "role": "admin",
                "permissions": {"manage_cameras": True, "view_live": True}, "site_ids": []}
        with pytest.raises(HTTPException) as ei:
            await api_discover(cam_id, user=user)
        assert ei.value.status_code == 401
        assert ei.value.detail["error"] == "authentication_failed"
        assert ei.value.detail["detail"]["auth_warning_info"]["remain_times"] == 8

        await db.cameras.delete_one({"id": cam_id})

    asyncio.run(run())
