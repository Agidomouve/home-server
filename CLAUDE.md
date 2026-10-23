# Home Server - Contexte Claude

## Vue d'ensemble

Serveur domotique sur Raspberry Pi gérant l'énergie solaire, le chauffage et les appareils connectés d'une maison en Suisse.

## Architecture

```
Raspberry Pi (192.168.1.133)
├── SSD NVMe Samsung (256 Go) : Système, configs, Docker (boot principal)
├── Carte SD (119 Go) : Ancien système, conservée comme boot de secours
└── Disque USB LaCie 4.5 To (/mnt/hdd) : Données InfluxDB, Grafana

NAS Synology (192.168.1.187 / QuickConnect: NAS-Ostie)
├── Photos de famille (dossier partagé commun)
├── Espaces privés par utilisateur
└── BackupHomeAssistant (backup HA via intégration Synology)
```

### Services Docker

| Service | Port | Stockage |
|---------|------|----------|
| Home Assistant | 8123 (host) | ./homeassistant |
| InfluxDB 2.6 | 8086 | /mnt/hdd/influxdb |
| Grafana | 3000 | /mnt/hdd/grafana |
| Mosquitto MQTT | 1883, 9001 | ./mosquitto |
| Node-RED | 1880 | ./nodered_data |
| Zigbee2MQTT | 8080 | ./zigbee2mqtt/data |
| OTBR (Thread) | 8081 (host) | ./otbr_data |
| Matter server (matter.js) | 5580 (host) | ./matter_data |
| Samba | host (137-138 UDP, 139, 445) | /mnt/hdd/photos, /mnt/hdd/cameras |
| FTP (caméras) | 21, 21000-21010 | /mnt/hdd/cameras |
| Portainer (supervision Docker) | 9443 (HTTPS) | ./portainer_data |
| Virtual plugs SolarManager (x13, MyStrom simulés) | macvlan 192.168.1.171-182, 190 | ./solar-manager-virtual-device |

### Intégrations principales

- **Fronius Symo** : Onduleur PV 15 kW
- **Stiebel Eltron ISG** : Pompe à chaleur
- **Askoheat+** : Chauffe-eau surplus solaire
- **go-eCharger** : Borne de recharge VE
- **ESPHome** : 8 smart plugs Swiss Domotique (dont « Lave vaisselle rez », zone Cuisine rez → `sensor.cuisine_rez_lave_vaisselle_rez_*`)
- **Prises virtuelles SolarManager** : conteneurs `solar-manager-virtual-device` (MyStrom Switch simulé) ; Node-RED (onglet *VirtualPlug - EspHome*) pousse la puissance HA via `POST http://<ip>/power` et peut lire `/report` pour piloter le switch HA. Le nom affiché se règle dans SolarManager (le champ `name` du JSON n'est pas lu). Dernière : `solar-virtual-LaveVaisselleRez` → 192.168.1.182
- **SLZB-MR5U** (192.168.1.156) : coordinateur Zigbee (radio 0, EmberZNet, `tcp://…:6638`) via Zigbee2MQTT, canal Zigbee 15 ; radio 1 = OpenThread RCP sur `tcp://…:7638` → conteneur `otbr` (forwarding IPv6 dans `/etc/sysctl.d/60-otbr.conf`), réseau Thread « MaisonRussy » canal 25 (créé via REST OTBR)
- **Synology NAS** : Intégration HA pour backup (user: HomeAssistant, droits admin)

## Convention de nommage des appareils

**Pièce + fonction + mesure** → `sensor.<pièce>_<fonction>_<mesure>` (ex. `sensor.salon_1er_climat_temperature`)

| Type | Nom à donner | Exemple d'entity_id |
|------|--------------|---------------------|
| Matter / intégrations HA | Zone HA = pièce, nom de l'appareil = fonction (« Climat ») — HA préfixe la zone | `sensor.toilettes_1er_climat_humidite` |
| Zigbee2MQTT | Friendly name Z2M = « <Pièce> <Fonction> » (Z2M fixe l'entity_id, pas la zone HA) + zone HA à attribuer | `sensor.chambre_2e_climat_humidity` |

Fonctions : `climat` (température/humidité), `vanne` (TRVZB, à venir). Les capteurs `*_climat_*` partent automatiquement dans InfluxDB et le dashboard « Climat intérieur ». Suffixes Matter en français (`_humidite`, `_batterie`).

**Capteurs climat installés :**
| Appareil | Protocole | Pièce |
|----------|-----------|-------|
| Sonoff SNZB-02DR2 (AirGuard TH) | Zigbee | Salon 1er, Chambre 2e, BabyRoom 2e |
| IKEA TIMMERFLOTTE | Matter/Thread | Salle de bains 2e, Toilettes 1er |

**Points techniques Zigbee/Thread :**
- Z2M `device_options.retain: true` : sans ça, les capteurs sur pile restent « inconnu » après un redémarrage de HA (Z2M ne renvoie pas les états)
- HA → InfluxDB n'écrit qu'au **changement** d'état : après un redémarrage, un capteur stable peut mettre un moment à réapparaître
- Matter : renommer l'appareil dans HA **et** accepter le renommage des entity_id (sinon l'ancien entity_id reste)
- OTBR embarque son propre mDNS → conflit avec avahi : le Pi s'annonce `raspberrypi-6.local` (sans impact, on utilise l'IP)
- Android « Réseaux Thread » affiche MaisonRussy « Indisponible » : cosmétique, l'appairage Matter fonctionne
- Images épinglées : `ownbee/hass-otbr-docker:v0.3.0`, `matter-js/matterjs-server:1.4.0` (python-matter-server est archivé)


## Fichiers importants

```
docker-compose.yml          # Orchestration services
homeassistant/
  configuration.yaml        # Config HA principale
  automations.yaml          # 119 automations
  secrets.yaml              # Secrets (non versionné)
  custom_components/        # Intégrations custom
grafana-dashboards/         # Export des dashboards (versionné)
zigbee2mqtt/data/           # Config Z2M (secret.yaml non versionné)
```

## Commandes fréquentes

```bash
# Services Docker
docker compose up -d
docker compose restart <service>
docker logs -f <service>

# Espace disque
df -h / /mnt/hdd

# Vérifier le disque de boot
findmnt / /boot/firmware

# Git (nécessite passphrase SSH)
git push origin main
```

## Points d'attention

- **SSH** : Clé protégée par passphrase, push manuel requis
- **Stockage** : Données volumineuses sur USB, système et configs sur SSD NVMe
- **Boot** : `BOOT_ORDER=0xf416` (NVMe → SD → USB). La carte SD reste en secours
- **Redémarrage Docker** : les conteneurs sont en `restart: unless-stopped` → après un arrêt manuel, relancer `docker compose up -d`
- **Montage USB** : Configuré dans /etc/fstab avec nofail
- **Grafana** : Credentials par défaut admin/admin123
- **Tarification** : Heures pleines 7h-23h (0.31 CHF), creuses 23h-7h (0.22 CHF)

## Ce qui n'est PAS versionné

- Données InfluxDB (séries temporelles)
- secrets.yaml, .env
- Bases de données (*.db)
- Logs

## TODO - Prochaines sessions

### Zigbee / Thread / chauffage
- [ ] Vannes Sonoff TRVZB (pas encore reçues) : appairer dans Z2M en « <Pièce> Vanne », ajouter globs InfluxDB + panneau Grafana, envoyer la température du capteur climat de la pièce à la vanne (`external_temperature_input`)
- [ ] Ampoules Philips Hue comme routeurs Zigbee : retirer du pont Hue, reset Touchlink, appairer dans Z2M (doivent rester alimentées)
- [ ] Sauvegarder vers le NAS : `zigbee2mqtt/data/` (dont `coordinator_backup.json` et `secret.yaml`), `otbr_data/`, `matter_data/` (clés réseau, non versionnés)
- [ ] Fixer l'IP du SLZB-MR5U (192.168.1.156) en bail DHCP statique sur le routeur

### Caméras Reolink (4 caméras)
- [x] Installer serveur FTP (Docker) - `delfer/alpine-ftp-server`
- [x] Créer structure `/mnt/hdd/cameras/{Atelier,Jardin-Terrasse,Garage-Russy,Cabanon}`
- [x] Configurer rétention automatique 90 jours (`/etc/cron.daily/cleanup-cameras`)
- [ ] Configurer chaque caméra pour envoyer les clips en FTP

**Config FTP pour caméras :**
| Paramètre | Valeur |
|-----------|--------|
| Serveur | 192.168.1.133 |
| Port | 21 |
| Utilisateur | camera |
| Mot de passe | camera123 |
| Dossiers | /Atelier, /Jardin-Terrasse, /Garage-Russy, /Cabanon |

### Partage réseau (Samba)
- [x] Installer Samba pour accès aux fichiers depuis le réseau local
- [x] Partager `/mnt/hdd/photos` et `/mnt/hdd/cameras`
- [x] Configurer network_mode: host pour NetBIOS (découverte réseau)
- [x] Créer utilisateurs Samba avec authentification
- [ ] **BUG** : Accès depuis Windows échoue (erreur 67) - fonctionne depuis macOS/iOS

**Config Samba :**
| Partage | Chemin | Accès |
|---------|--------|-------|
| Photos | /mnt/hdd/photos | Lecture/Écriture |
| Cameras | /mnt/hdd/cameras | Lecture seule |

| Utilisateur | Mot de passe |
|-------------|--------------|
| photos | photos123 |
| camera | camera123 |

**Connexion** : `smb://192.168.1.133/Photos` (macOS/iOS fonctionne, Windows à débugger)

### NAS Synology
- [x] NAS installé (192.168.1.187, QuickConnect: NAS-Ostie)
- [x] Dossier partagé Photos de famille (commun)
- [x] Espaces privés par utilisateur
- [x] Intégration Synology dans HA (backup sur dossier BackupHomeAssistant)
- [x] User HomeAssistant créé avec droits admin
- [x] Montage NFS4 du dossier BackupPi sur `/mnt/nas-backup` (fstab, persistant)

**NFS :** Le Pi a deux IPs sur le réseau local (`192.168.1.133` eth0 et `192.168.1.200` macvlan-shim ; anciennement `.250`) — les deux sont autorisées côté NAS.

### Backup automatique
- [x] Backup Home Assistant via intégration Synology → NAS dossier BackupHomeAssistant
- [x] Backup InfluxDB quotidien (2h du matin) → NAS `/mnt/nas-backup/influxdb/`, rétention 7 jours
- [ ] Configurer backup Grafana et autres configs vers NAS

**Config backup InfluxDB :**
| Paramètre | Valeur |
|-----------|--------|
| Script | `/usr/local/bin/backup-influxdb.sh` |
| Cron | `/etc/cron.d/backup-influxdb` (tous les jours à 2h) |
| Destination | `/mnt/nas-backup/influxdb/YYYY-MM-DD_HHMM/` |
| Rétention | 7 jours |
| Log | `/var/log/backup-influxdb.log` |
| Token | Operator token (limad's Token) |

### Tarifs Groupe E
- [x] Cron `/etc/cron.d/groupe-e-tarifs` (15h05, 17h05, 20h05, user limad, log `/var/log/groupe-e-tarifs.log`)
- [ ] Coller la carte `homeassistant/cards/tarifs_groupe_e.yaml` dans un tableau de bord HA

### go-eCharger — Migration Modbus → MQTT (EN COURS)

**Contexte** : Le go-eCharger (192.168.1.107, Modbus TCP port 502) crashait à cause de trop de clients simultanés : SolarManager (HTTP) + HA (MQTT via goecharger_mqtt) + Node-RED (Modbus). La borne nécessitait un reboot physique (coupure Devolo).

**Fix temporaire appliqué** : `emptyMsgOnFail=false` sur le node modbus-read GoE → plus de crash buffer-parser. Le node modbus-read GoE est actuellement **désactivé** (`d: true`).

**Objectif** : Remplacer le flow Modbus GoE par une souscription MQTT, pour éliminer une connexion TCP supplémentaire.

**Données MQTT disponibles** :
| Topic | Contenu |
|-------|---------|
| `go-eCharger/405603/nrg` | Tableau JSON [V_L1, V_L2, V_L3, V_N, A_L1, A_L2, A_L3, P_L1, P_L2, P_L3, P_N, P_Total, PF_L1...] |
| `go-eCharger/405603/wh` | Énergie chargée session (Wh) |

**État actuel** : Les nodes MQTT sont dans flows.json (ids: c9f1a2b3d4e5000[1-5]) mais pas connectés — le problème est les credentials MQTT qui ne peuvent pas être injectés depuis CLI (chiffrés dans flows_cred.json).

**À faire lors de la prochaine session** (2 options) :
- [ ] **Option A (recommandée)** : Via l'UI Node-RED, configurer le broker MQTT `Mosquitto_local` (déjà dans flows.json) avec user=`nodered` / password=`nodered123`, puis activer les nodes GoE_nrg et GoE_wh
- [ ] **Option B** : Utiliser HA comme source de données → envoyer les entités go-eCharger vers InfluxDB via l'intégration InfluxDB de HA

**User MQTT créé** : `nodered` / `nodered123` dans `/home/limad/home-server/mosquitto/config/passwordfile`

### go-eCharger — `switch.vélo_switch` (EN COURS)
- [ ] Corriger l'entity_id avec accent `é` dans Node-RED UI (node `api-call-service:ON` dans tab VirtualPlug-EspHome)

## Historique des modifications

- **2026-10-20** : Ajout Portainer CE (`portainer/portainer-ce:lts`, https://192.168.1.133:9443) pour superviser les conteneurs depuis le navigateur

- **2026-10-23** : Prise ESPHome « Lave vaisselle rez » ajoutée à SolarManager : prise virtuelle `solar-virtual-LaveVaisselleRez` (192.168.1.182) + flux Node-RED (`sensor.cuisine_rez_lave_vaisselle_rez_power` → `/power`, pilotage ON/OFF désactivé comme pour le lave-vaisselle du haut) ; correction de l'entity_id du switch « Lave-Vaiselle Haut » dans Node-RED

- **2026-10-18** : Tarifs Groupe E (API publique `https://api.tariffs.groupe-e.ch/v2/tariffs`, `tariff_name=double|vario`, pas 15 min, publication J+1 vers 14h50, historique depuis le 01.01.2026) : `scripts/fetch_groupe_e_tariffs.py` → InfluxDB mesure `groupe_e_tarif` (tag `tariff`, champs `price` TTC ×1.081 / `grid` / `price_ht`), prix de demain inclus ; dashboard Grafana « Tarifs Groupe E » (`grafana-dashboards/build_tarifs_groupe_e.py` : prix aujourd'hui/demain, coût Double vs Vario sur le soutirage réel) ; côté HA, les capteurs `sensor.groupee_vario` / `sensor.groupee_double` viennent de l'intégration HACS `sgr_dyntariff` (attributs `today`/`tomorrow`), carte apexcharts dans `homeassistant/cards/tarifs_groupe_e.yaml`
- **2026-10-17** : Ajout Zigbee2MQTT (conteneur, user MQTT `zigbee2mqtt`, secrets dans `zigbee2mqtt/data/secret.yaml` non versionné) sur le SLZB-MR5U ; capteurs climat (Sonoff SNZB-02DR2) envoyés vers InfluxDB (globs `sensor.*_climat_*`, voir convention de nommage) ; ajout conteneurs `otbr` + `matter-server` pour Thread/Matter (1er appareil : IKEA TIMMERFLOTTE) ; dashboard Grafana « Climat intérieur » (`grafana-dashboards/build_climat_interieur.py`, pièces découvertes automatiquement) ; convention de nommage pièce + fonction + mesure, historique climat InfluxDB remis à zéro après renommage
- **2026-10-16** : InfluxDB alimenté par HA via `entity_globs` (PV, prises, PAC, Askoheat, CE-Boiler, borne 411884, tarifs) ; import de l'historique HA (`scripts/import_ha_history.py` : états bruts 10 j + statistiques horaires depuis 09/2025, ~5,7 M points) ; dashboard Grafana « Énergie maison » (`grafana-dashboards/build_energie_maison.py`)
- **2026-10-16** : Migration système carte SD → SSD NVMe Samsung 256 Go (boot NVMe vérifié, carte SD conservée en secours), relance de la stack Docker
- **2026-03-05** : Fix crashes go-eCharger (emptyMsgOnFail=false sur 4 nodes Modbus), correction chemins /root/.node-red/ → /data/ dans Node-RED, création user MQTT nodered
- **2026-01-29** : Ajout NAS Synology (192.168.1.187, QuickConnect NAS-Ostie), montage NFS4 BackupPi, backup automatique InfluxDB quotidien (2h, rétention 7j, ~456 Mo), backup HA via intégration Synology
- **2026-01-15** : Ajout serveur FTP pour caméras Reolink, configuration Samba (network_mode host, utilisateurs, partage Cameras), debug accès Windows en cours
- **2026-01-14** : Migration InfluxDB et Grafana vers disque USB, export dashboards, nettoyage Docker (~9 Go récupérés), création CLAUDE.md
