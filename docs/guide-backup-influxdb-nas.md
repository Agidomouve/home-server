# Guide : Backup InfluxDB vers NAS Synology

## Vue d'ensemble

Ce guide documente la mise en place du backup automatique d'InfluxDB (Raspberry Pi) vers un NAS Synology via NFS.

```
┌──────────────────┐         NFS (port 2049)        ┌──────────────────┐
│  Raspberry Pi    │ ─────────────────────────────── │  NAS Synology    │
│  192.168.1.133   │                                 │  192.168.1.187   │
│                  │                                 │                  │
│  InfluxDB        │  Chaque nuit à 2h               │  /BackupPi/      │
│  (Docker)        │  ──────────────────────────────► │   influxdb/      │
│                  │  backup ~456 Mo                 │    2026-01-29/   │
│                  │                                 │    2026-01-30/   │
│                  │                                 │    ...           │
└──────────────────┘                                 └──────────────────┘
```

---

## Partie 1 : Préparation du NAS Synology

### 1.1 Créer le dossier partagé

1. Ouvrir DSM dans le navigateur : `http://192.168.1.187:5000`
2. Aller dans **Panneau de configuration → Dossier partagé**
3. Cliquer **Créer**
4. Nom : `BackupPi`

### 1.2 Activer le service NFS

1. **Panneau de configuration → Services de fichiers → NFS**
2. Cocher **Activer le service NFS**
3. Protocole maximum : **NFSv4.1**
4. Cocher **Autoriser les connexions depuis des ports non-privilégiés** (important !)

### 1.3 Configurer les permissions NFS sur le dossier

1. **Panneau de configuration → Dossier partagé → BackupPi → Modifier**
2. Onglet **Permissions NFS**
3. Créer **deux règles** (le Pi a deux adresses IP) :

| Règle | IP | Privilège | Squash | Sécurité |
|-------|-----|-----------|--------|----------|
| 1 | `192.168.1.133/32` | Lecture/Écriture | Pas de mappage | sys |
| 2 | `192.168.1.250/32` | Lecture/Écriture | Pas de mappage | sys |

> **Pourquoi deux IPs ?**
> Le Pi a son IP principale (`192.168.1.133` sur eth0) et une seconde IP
> (`192.168.1.250` sur macvlan-shim) utilisée par les smart plugs ESPHome.
> Linux peut choisir l'une ou l'autre comme adresse source. Les deux doivent
> être autorisées sinon on obtient "access denied".

### 1.4 Créer un utilisateur dédié (optionnel)

1. **Panneau de configuration → Utilisateur et groupe → Créer**
2. Nom : `RaspberryPi-Home-server`
3. Lui donner Lecture/Écriture sur le dossier `BackupPi`

> **Note :** NFS n'utilise pas les utilisateurs Synology pour l'authentification.
> Le contrôle d'accès se fait par adresse IP. L'utilisateur sert uniquement
> pour l'accès via d'autres protocoles (SMB, etc.).

---

## Partie 2 : Configuration du Raspberry Pi

### 2.1 Vérifier que le client NFS est installé

```bash
dpkg -l | grep nfs-common
```

Si pas installé :
```bash
sudo apt install nfs-common
```

### 2.2 Vérifier que le NAS expose bien le partage

```bash
showmount -e 192.168.1.187
```

Résultat attendu :
```
Export list for 192.168.1.187:
/volume1/BackupPi 192.168.1.133/32,192.168.1.250/32
```

### 2.3 Créer le point de montage et monter

```bash
# Créer le dossier local
sudo mkdir -p /mnt/nas-backup

# Monter le partage NFS
sudo mount -t nfs4 192.168.1.187:/volume1/BackupPi /mnt/nas-backup

# Vérifier
df -h /mnt/nas-backup
```

### 2.4 Tester l'écriture

```bash
sudo touch /mnt/nas-backup/test && sudo rm /mnt/nas-backup/test
echo "OK si aucune erreur"
```

### 2.5 Rendre le montage permanent (fstab)

Ajouter cette ligne à `/etc/fstab` :

```
192.168.1.187:/volume1/BackupPi  /mnt/nas-backup  nfs4  defaults,nofail,_netdev  0  0
```

Les options importantes :
- `nofail` : si le NAS est éteint ou injoignable, le Pi démarre quand même
- `_netdev` : attend que le réseau soit prêt avant de tenter le montage

---

## Partie 3 : Script de backup InfluxDB

### 3.1 Le script

Emplacement : `/usr/local/bin/backup-influxdb.sh`

```bash
#!/bin/bash
# Backup InfluxDB vers NAS Synology
# Fréquence : quotidien via cron
# Rétention : 7 jours

BACKUP_DIR="/mnt/nas-backup/influxdb"
DATE=$(date +%Y-%m-%d_%H%M)
RETENTION_DAYS=7
TOKEN="<token operator InfluxDB>"
LOG="/var/log/backup-influxdb.log"

# Vérifier que le NAS est monté
if ! mountpoint -q /mnt/nas-backup; then
    echo "$(date) ERREUR: NAS non monté, tentative de montage..." >> $LOG
    mount /mnt/nas-backup
    if ! mountpoint -q /mnt/nas-backup; then
        echo "$(date) ERREUR: Impossible de monter le NAS" >> $LOG
        exit 1
    fi
fi

# Créer le dossier de backup du jour
mkdir -p "$BACKUP_DIR/$DATE"

# Exécuter le backup InfluxDB dans le container
docker exec influxdb influx backup /tmp/backup-$DATE \
    --host http://localhost:8086 \
    --token "$TOKEN" 2>> $LOG

# Copier les fichiers depuis le container vers le NAS
docker cp influxdb:/tmp/backup-$DATE/. "$BACKUP_DIR/$DATE/"
RESULT=$?

# Nettoyer dans le container
docker exec influxdb rm -rf /tmp/backup-$DATE

if [ $RESULT -eq 0 ]; then
    SIZE=$(du -sh "$BACKUP_DIR/$DATE" | cut -f1)
    echo "$(date) OK: Backup $DATE créé ($SIZE)" >> $LOG
else
    echo "$(date) ERREUR: Backup $DATE échoué" >> $LOG
    rm -rf "$BACKUP_DIR/$DATE"
    exit 1
fi

# Supprimer les backups de plus de 7 jours
find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +$RETENTION_DAYS \
    -exec rm -rf {} \;
echo "$(date) Nettoyage: backups > ${RETENTION_DAYS}j supprimés" >> $LOG
```

### 3.2 Comment ça fonctionne, étape par étape

1. **Vérification du NAS** : le script vérifie que `/mnt/nas-backup` est bien monté. Si non, il tente de le monter.
2. **Backup dans le container** : `influx backup` crée un export complet de toutes les données dans `/tmp/` à l'intérieur du container Docker.
3. **Copie vers le NAS** : `docker cp` copie les fichiers du container vers le dossier NAS.
4. **Nettoyage container** : supprime les fichiers temporaires dans le container.
5. **Rotation** : supprime les backups de plus de 7 jours sur le NAS.

### 3.3 Le token InfluxDB

Le backup nécessite le **token operator** (créé à l'installation d'InfluxDB), pas un token "All Access" limité à une organisation.

Pour lister les tokens :
```bash
docker exec influxdb influx auth list \
    --host http://localhost:8086 \
    --token "<un token valide>"
```

Le bon token est celui qui a des permissions **globales** comme `read:/authorizations` (sans le préfixe `orgs/...`).

### 3.4 Rendre exécutable

```bash
sudo chmod +x /usr/local/bin/backup-influxdb.sh
```

---

## Partie 4 : Planification automatique (Cron)

### 4.1 Créer la tâche cron

```bash
echo '0 2 * * * root /usr/local/bin/backup-influxdb.sh' | sudo tee /etc/cron.d/backup-influxdb
```

Explication : `0 2 * * *` = chaque jour à 2h00 du matin.

### 4.2 Vérifier que le cron est actif

```bash
cat /etc/cron.d/backup-influxdb
```

---

## Partie 5 : Vérification et maintenance

### Consulter les logs

```bash
cat /var/log/backup-influxdb.log
```

Exemple de log normal :
```
Thu 29 Jan 19:27:44 GMT 2026 OK: Backup 2026-01-29_1926 créé (456M)
Thu 29 Jan 19:27:44 GMT 2026 Nettoyage: backups > 7j supprimés
```

### Lister les backups sur le NAS

```bash
ls -lh /mnt/nas-backup/influxdb/
```

### Lancer un backup manuellement

```bash
sudo /usr/local/bin/backup-influxdb.sh
```

### Vérifier que le NAS est monté

```bash
df -h /mnt/nas-backup
```

Si le NAS n'est pas monté (après un redémarrage ou une coupure réseau) :
```bash
sudo mount /mnt/nas-backup
```

---

## Partie 6 : Restauration (en cas de problème)

Si InfluxDB perd ses données, voici comment restaurer depuis un backup :

```bash
# 1. Choisir le backup à restaurer
ls /mnt/nas-backup/influxdb/

# 2. Copier le backup dans le container
docker cp /mnt/nas-backup/influxdb/2026-01-29_1926/. influxdb:/tmp/restore/

# 3. Restaurer (ATTENTION : écrase les données actuelles)
docker exec influxdb influx restore /tmp/restore/ \
    --host http://localhost:8086 \
    --token "<token operator>" \
    --full

# 4. Nettoyer
docker exec influxdb rm -rf /tmp/restore/
```

> **Attention :** La restauration complète (`--full`) écrase toutes les données
> existantes. Ne le faire que si nécessaire.

---

## Résumé des fichiers et emplacements

| Élément | Emplacement |
|---------|-------------|
| Script de backup | `/usr/local/bin/backup-influxdb.sh` |
| Tâche cron | `/etc/cron.d/backup-influxdb` |
| Point de montage NAS | `/mnt/nas-backup` |
| Backups InfluxDB | `/mnt/nas-backup/influxdb/YYYY-MM-DD_HHMM/` |
| Logs | `/var/log/backup-influxdb.log` |
| Config montage permanent | `/etc/fstab` (dernière ligne) |

## Dépannage

| Problème | Cause probable | Solution |
|----------|---------------|----------|
| `access denied by server` au montage | IP non autorisée dans les permissions NFS du NAS | Vérifier les deux IPs (133 et 250) dans les permissions NFS |
| `Permission denied` en écriture | Squash mal configuré | Mettre "Pas de mappage" dans les permissions NFS |
| `401 Unauthorized` au backup | Mauvais token InfluxDB | Utiliser le token operator (global), pas un token All Access |
| NAS non monté après reboot | Réseau pas prêt | Le `nofail` dans fstab empêche le blocage, remonter manuellement |
| Backup de taille 0 | Token sans droits suffisants | Vérifier les logs, utiliser le token operator |
