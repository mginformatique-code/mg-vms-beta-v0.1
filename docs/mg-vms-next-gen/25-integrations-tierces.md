# Chapitre 25 — Intégrations tierces stratégiques

> **Version** : v1.0 · **Date** : 2026-07-24

Ce chapitre liste les **intégrations tierces prioritaires** livrées comme plugins officiels ou vérifiés sur le Marketplace. Elles ancrent MG-VMS dans les écosystèmes existants (domotique, monitoring, ITSM).

## 25.1 Home Assistant

Plugin `home-assistant-integration` — bidirectionnel MQTT :
- MG-VMS publie : status caméras, événements IA, plaques, occupation parking.
- MG-VMS consomme : states HA (user_absent, alarm_armed, night_mode) pour conditionner ses automatisations.
- Config UI par mapping topic ↔ entité HA.

## 25.2 Grafana

Plugin `grafana-datasource` — expose les métriques MG-VMS comme datasource Prometheus / JSON API :
- Événements par heure/caméra.
- Occupation parking.
- Uptime caméras.
- Stats plugins (CPU/RAM/latence).

Dashboards Grafana templates fournis (import JSON).

## 25.3 Node-RED

Plugin `nodered-nodes` (package npm `node-red-contrib-mgvms`) :
- Nodes triggers : `mgvms-event`, `mgvms-alert`, `mgvms-plate`.
- Nodes actions : `mgvms-snapshot`, `mgvms-ptz`, `mgvms-notify`.

Permet à un utilisateur Node-RED de construire des flows sans coder.

## 25.4 Frigate

Plugin `frigate-integration` — cohabitation MG-VMS ↔ Frigate :
- Import événements Frigate dans MG-VMS.
- MG-VMS peut consommer les détections Frigate (utile si utilisateur a déjà Frigate en place).
- Migration douce Frigate → MG-VMS (import config caméras).

## 25.5 Jeedom

Plugin `jeedom-integration` — pour la domotique française populaire :
- Bridge via API Jeedom.
- Utilisateur MG-VMS peut voir dans Jeedom : caméras, alertes, snapshots.
- Actions Jeedom déclenchables depuis MG-VMS.

## 25.6 OpenHAB

Plugin `openhab-integration` — similaire Home Assistant via REST OpenHAB + MQTT.

## 25.7 KNX

Plugin `knx-integration` — bâtiments professionnels :
- Bridge KNX/IP.
- MG-VMS peut actionner relais (portes, lumières) via commandes KNX groups.
- Consommer événements KNX comme triggers automation.

## 25.8 BACnet

Plugin `bacnet-integration` — GTB (Gestion Technique du Bâtiment) :
- BACnet/IP client.
- MG-VMS peut publier ses métriques comme objets BACnet consommables par GTB centralisée.

## 25.9 Modbus

Plugin `modbus-integration` — industriel :
- Modbus TCP client.
- Actionner relais physiques via Modbus (sirènes, portails).

## 25.10 Prometheus / InfluxDB

Plugins `prometheus-exporter` et `influxdb-exporter` — export métriques pour monitoring pro.

## 25.11 Slack / Teams / Signal / WhatsApp / Pushover

Plugins notifiers spécialisés (marketplace) — au-delà du bundle SMTP/Discord/Telegram.

## 25.12 SIEM (Splunk, Elastic)

Plugin `siem-forwarder` — envoie les événements audit + alertes vers SIEM entreprise (Syslog, HTTP JSON).

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
