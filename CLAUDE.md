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
| Samba | host (137-138 UDP, 139, 445) | /mnt/hdd/photos, /mnt/hdd/cameras |
| FTP (caméras) | 21, 21000-21010 | /mnt/hdd/cameras |
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

## TODO - Prochaines sessions

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

### Backup automatique
- [ ] Définir stratégie de backup (destination, fréquence)
- [ ] Configurer backup des configs et données critiques

## Historique des modifications

- **2026-01-15** : Ajout serveur FTP pour caméras Reolink, configuration Samba (network_mode host, utilisateurs, partage Cameras), debug accès Windows en cours
- **2026-01-14** : Migration InfluxDB et Grafana vers disque USB, export dashboards, nettoyage Docker (~9 Go récupérés), création CLAUDE.md
