# Home Server - Contexte Claude

## Vue d'ensemble

Serveur domotique sur Raspberry Pi gérant l'énergie solaire, le chauffage et les appareils connectés d'une maison en Suisse.

## Architecture

```
Raspberry Pi
├── Carte SD (117 Go) : Système, configs, Docker
└── Disque USB LaCie 4.5 To (/mnt/hdd) : Données InfluxDB, Grafana
```

### Services Docker

| Service | Port | Stockage |
|---------|------|----------|
| Home Assistant | 8123 (host) | ./homeassistant |
| InfluxDB 2.6 | 8086 | /mnt/hdd/influxdb |
| Grafana | 3000 | /mnt/hdd/grafana |
| Mosquitto MQTT | 1883, 9001 | ./mosquitto |
| Node-RED | 1880 | ./nodered_data |
| Virtual plugs (x9) | macvlan 192.168.1.171-190 | - |

### Intégrations principales

- **Fronius Symo** : Onduleur PV 15 kW
- **Stiebel Eltron ISG** : Pompe à chaleur
- **Askoheat+** : Chauffe-eau surplus solaire
- **go-eCharger** : Borne de recharge VE
- **ESPHome** : 7 smart plugs Swiss Domotique

## Fichiers importants

```
docker-compose.yml          # Orchestration services
homeassistant/
  configuration.yaml        # Config HA principale
  automations.yaml          # 119 automations
  secrets.yaml              # Secrets (non versionné)
  custom_components/        # Intégrations custom
grafana-dashboards/         # Export des dashboards (versionné)
```

## Commandes fréquentes

```bash
# Services Docker
docker compose up -d
docker compose restart <service>
docker logs -f <service>

# Espace disque
df -h / /mnt/hdd

# Git (nécessite passphrase SSH)
git push origin main
```

## Points d'attention

- **SSH** : Clé protégée par passphrase, push manuel requis
- **Stockage** : Données volumineuses sur USB, configs sur SD
- **Montage USB** : Configuré dans /etc/fstab avec nofail
- **Grafana** : Credentials par défaut admin/admin123
- **Tarification** : Heures pleines 7h-23h (0.31 CHF), creuses 23h-7h (0.22 CHF)

## Ce qui n'est PAS versionné

- Données InfluxDB (séries temporelles)
- secrets.yaml, .env
- Bases de données (*.db)
- Logs

## Historique des modifications

- **2026-01-14** : Migration InfluxDB et Grafana vers disque USB, export dashboards, nettoyage Docker (~9 Go récupérés)
