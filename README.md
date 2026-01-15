# Home Server - Documentation

Serveur domotique sur Raspberry Pi gérant l'énergie solaire, le chauffage et les appareils connectés.

## Architecture Globale

```
┌─────────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI (Docker)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Home      │  │  Mosquitto  │  │       Node-RED          │ │
│  │  Assistant  │◄─┤    MQTT     │◄─┤  (Modbus, Automations)  │ │
│  │  (host)     │  │  :1883      │  │       :1880             │ │
│  └──────┬──────┘  └─────────────┘  └─────────────────────────┘ │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────┐  ┌─────────────┐                              │
│  │  InfluxDB   │◄─┤   Grafana   │                              │
│  │   :8086     │  │   :3000     │                              │
│  │  (USB HDD)  │  │  (USB HDD)  │                              │
│  └─────────────┘  └─────────────┘                              │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           Réseau macvlan (192.168.1.171-190)            │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐      ┌────────────┐   │   │
│  │  │ Plug 1 │ │ Plug 2 │ │  ...   │ ...  │  BoilerCE  │   │   │
│  │  │  .171  │ │  .172  │ │        │      │    .190    │   │   │
│  │  └────────┘ └────────┘ └────────┘      └────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Services Docker

| Service | Image | Port | Description |
|---------|-------|------|-------------|
| **homeassistant** | ghcr.io/home-assistant/home-assistant:stable | host | Domotique centrale |
| **influxdb** | influxdb:2.6 | 8086 | Base de données temporelles |
| **grafana** | grafana/grafana:latest | 3000 | Dashboards et visualisation |
| **mosquitto** | eclipse-mosquitto:2 | 1883, 9001 | Broker MQTT |
| **nodered** | nodered/node-red:latest | 1880 | Automations et Modbus |
| **solar-virtual-plug1-8** | node:alpine | macvlan | Émulation prises MyStrom |
| **solar-virtual-BoilerCE** | node:alpine | macvlan | Émulation chauffe-eau |
| **samba** | dperson/samba | 139, 445 | Partage de fichiers réseau |

## Intégrations Home Assistant

### Équipements Énergétiques

| Intégration | Type | Description |
|-------------|------|-------------|
| **Fronius Symo 15.0-3-M** | Onduleur PV | Production solaire |
| **Smart Meter TS 65A-3** | Compteur | Consommation/injection réseau |
| **Stiebel Eltron ISG** | Pompe à chaleur | Chauffage et ECS |
| **Askoheat+** | Chauffe-eau | Surplus solaire vers ECS |
| **go-eCharger** | Borne de charge | Recharge véhicule électrique |

### Appareils Connectés

| Intégration | Quantité | Description |
|-------------|----------|-------------|
| **ESPHome** | 7 | Swiss Domotique Smart Plugs (suivi conso) |
| **Virtual MyStrom** | 9 | Émulation pour Solar Manager |

## Stockage

| Emplacement | Contenu | Support |
|-------------|---------|---------|
| `/` | Configs, Home Assistant, Node-RED | Carte SD (117 Go) |
| `/mnt/hdd` | InfluxDB, Grafana, Photos | Disque USB (4.5 To) |

Les données volumineuses (séries temporelles, dashboards) sont sur le disque USB pour :
- Meilleures performances I/O
- Préserver la durée de vie de la carte SD
- Éviter les erreurs "database locked"

## Structure des Fichiers

```
home-server/
├── docker-compose.yml          # Orchestration des services
├── homeassistant/
│   ├── configuration.yaml      # Config principale HA
│   ├── automations.yaml        # 119 automations
│   ├── secrets.yaml            # Secrets (non versionné)
│   └── custom_components/      # Intégrations custom
│       ├── askoheat/
│       ├── goecharger_mqtt/
│       ├── stiebel_eltron_isg/
│       └── hacs/
├── nodered_data/
│   ├── flows.json              # Flows Node-RED
│   └── settings.js
├── mosquitto/
│   └── config/
│       └── mosquitto.conf
├── grafana-dashboards/         # Export des dashboards
│   ├── solar-pv-system.json
│   ├── pv.json
│   └── datasources.json
├── samba/
│   └── smb.conf                # Config partage réseau
└── solar-manager-virtual-device/
    ├── plug1.json ... plug8.json
    └── BoilerCE.json
```

## Réseau

### Ports Exposés

| Port | Service | Protocole |
|------|---------|-----------|
| 1880 | Node-RED | HTTP |
| 1883 | Mosquitto | MQTT |
| 3000 | Grafana | HTTP |
| 8086 | InfluxDB | HTTP |
| 8123 | Home Assistant | HTTP |
| 9001 | Mosquitto | WebSocket |
| 139 | Samba | NetBIOS |
| 445 | Samba | SMB |

### Réseau macvlan (Solar Manager)

Les plugs virtuels utilisent un réseau macvlan pour avoir des IPs sur le LAN :

| Appareil | IP |
|----------|-----|
| Plug 1-8 | 192.168.1.171-178 |
| BoilerCE | 192.168.1.190 |

## Partage Photos (Samba)

Le partage réseau permet d'accéder aux photos depuis tous les appareils du réseau local.

| Données | Emplacement |
|---------|-------------|
| Photos | `/mnt/hdd/photos` |

### Connexion depuis les appareils

| Appareil | Méthode |
|----------|---------|
| **Windows** | Explorateur de fichiers → `\\192.168.1.133\Photos` |
| **macOS** | Finder → Aller → Se connecter au serveur → `smb://192.168.1.133/Photos` |
| **iPad/iPhone** | App Fichiers → ⋯ → Se connecter au serveur → `smb://192.168.1.133/Photos` → Invité |
| **Linux** | `smb://192.168.1.133/Photos` ou mount CIFS |

> **Note** : Accès en lecture/écriture sans authentification (réseau local uniquement).

## Gestion de l'Énergie

### Tarification Électrique

Deux tarifs configurés (CHF/kWh) :
- **Heures pleines** (7h-23h) : 0.31
- **Heures creuses** (23h-7h) : 0.22

### Utility Meters

Compteurs configurés avec cycles :
- Journalier
- Mensuel
- Trimestriel
- Annuel

## Commandes Utiles

```bash
# Démarrer tous les services
docker compose up -d

# Voir les logs d'un service
docker logs -f homeassistant

# Redémarrer un service
docker compose restart grafana

# État des conteneurs
docker ps

# Espace disque
df -h /mnt/hdd
```

## Backup

### Versionné dans Git
- Configurations (docker-compose, HA, Node-RED, Mosquitto)
- Dashboards Grafana (exports JSON)
- Custom components

### Non versionné (à sauvegarder séparément)
- Données InfluxDB (`/mnt/hdd/influxdb`)
- Secrets (`secrets.yaml`, `.env`)
- Base de données Home Assistant

## Credentials par Défaut

| Service | User | Password |
|---------|------|----------|
| Grafana | admin | admin123 |

> **Note** : Changer les mots de passe par défaut en production.
