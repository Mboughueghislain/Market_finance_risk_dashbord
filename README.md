# Dashboard Risques Financiers

Application Streamlit de suivi des risques financiers pour la Direction des Risques.

---

## Fonctionnalités

### Onglets principaux
| Onglet | Description |
|---|---|
| **Suivi du Portefeuille** | Vue globale du portefeuille, détail par titre avec filtres avancés |
| **Suivi des risques** | Graphiques par risque et canton (Suivi Marché, Risque SDG, KPI) |
| **Data** | Tableau brut des données filtrées |
| **Rapport** | Synthèse exportable |

### Suivi des risques — structure des onglets dynamiques

Les onglets et sous-onglets sont générés automatiquement depuis le fichier Excel
`PICTURE/Liste des images pour Streamlit.xlsm` (feuille Parametres).

| Colonne Excel | Rôle |
|---|---|
| **Onglet Python** | Code interne identifiant l'onglet principal |
| **Libellé** | Nom affiché dans l'onglet Streamlit |
| **Sous-Onglet Python** | Nom du sous-onglet (`N` = pas de sous-onglet) |
| **Périmètre** | `Y` = canton dans le nom de fichier, `N` = date seule |
| **Nom de l'image** | Partie fixe du nom de fichier |
| **Titre Graphique** | Titre affiché au-dessus de l'image |
| **Ordre** | Ordre d'affichage dans l'onglet |
| **extension** | `png` ou `html` |
| **largeur** | `999` = pleine largeur, autre valeur = 2 images côte à côte |

### Convention de nommage des fichiers images

| Périmètre | Format du nom de fichier |
|---|---|
| `N` | `{YYYYMMDD}_{Nom_image}.{ext}` |
| `Y` | `{YYYYMMDD}_{CANTON}_{Nom_image}.{ext}` |

Exemples :
```
20260630_SDG_Suivi Marché.png          (Périmètre N)
20260630_CGP_AG_VALO_GRAPH1.png        (Périmètre Y, canton CGP AG)
```

### Affichage selon le filtre canton

| Filtre sidebar | Comportement |
|---|---|
| **Canton unique** (CGP AG, CGP RS, BPCEM AG) | Image centrée sur les 2/3 de la page |
| **EPS** (tous les cantons) | 3 colonnes côte à côte : CGP AG \| CGP RS \| BPCEM AG |

Les fichiers `.html` sont affichés en iframe (hauteur 600 px), les `.png` comme images.
Les images et fichiers HTML sont mis en cache mémoire 5 minutes pour limiter les lectures réseau.

---

## Sources de données

| Source | Chemin (réseau) | Usage |
|---|---|---|
| Données portefeuille | `/mnt/risques/.../` fichiers JSON | Tous les onglets sauf Suivi des risques |
| Excel paramètres images | `PICTURE/Liste des images pour Streamlit.xlsm` | Structure onglets/sous-onglets Suivi des risques |
| Images | `PICTURE/RAPPORT/{date}_{canton}_{nom}.png` | Graphiques Suivi des risques |

Les chemins se configurent dans l'onglet **Admin > Paramètres**.

---

## Configuration des chemins par poste

Chaque PC peut avoir ses propres chemins (lecteur réseau mappé différemment selon la machine) sans créer de conflit au `git pull`.

### Comment ça fonctionne

- `data/app_config.json` — configuration partagée (utilisateurs, paramètres métier) — **versionnée dans git**
- `data/app_config.local.json` — chemins propres à cette machine — **ignorée par git**

Au démarrage, l'application fusionne les deux fichiers : le fichier local a la priorité sur le fichier partagé pour les chemins.

### Configurer les chemins sur un nouveau poste

1. Lancer l'application (`streamlit run home.py`)
2. Se connecter en tant qu'Admin
3. Aller dans **Admin > Paramètres**
4. Renseigner les chemins **PICTURE** et **ARCHIVES** corrects pour ce poste
5. Sauvegarder — les chemins sont écrits dans `app_config.local.json` (jamais écrasés par `git pull`)

### Exemple de chemins WSL selon le lecteur réseau mappé

| Lecteur Windows | Chemin WSL à saisir |
|---|---|
| `H:\Direction des Risques\...\PICTURE` | `/mnt/h/Direction des Risques/4. Risques Financiers/00-0-REPORTING/00 - PROD RRF/Suivi Risques/PICTURE` |
| `Z:\4. Risques Financiers\...\PICTURE` | `/mnt/z/4. Risques Financiers/00-0-REPORTING/00 - PROD RRF/Suivi Risques/PICTURE` |

> Le chemin UNC `\\sv61file0024\Bureautique\...` fonctionne aussi si le partage réseau est accessible directement depuis WSL.

---

## Lancement

### WSL (recommandé)

```bash
cd /home/ghislain/risk_dashboard
source venv/bin/activate
cd dashboard
streamlit run home.py
```

Ou avec accès réseau exposé :
```bash
streamlit run home.py --server.address 0.0.0.0 --server.headless true
```

### Windows (CMD)

```cmd
cd C:\Users\ghisl\Desktop\risk_dashboard
.venv\Scripts\activate.bat
streamlit run dashboard\home.py
```

### Créer le venv (première fois)

**WSL :**
```bash
cd /home/ghislain/risk_dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (CMD) :**
```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

---

## Montage du répertoire réseau (WSL)

### Configuration permanente (fstab)

```bash
sudo nano /etc/fstab
```

Ajouter (les espaces s'écrivent `\040`) :
```
\\sv61file0024\Bureautique\Direction\040des\040Risques  /mnt/risques  drvfs  defaults,metadata  0  0
```

Activer sans redémarrer :
```bash
sudo mount -a
ls /mnt/risques
```

Activer wsl.conf pour le montage automatique :
```bash
sudo nano /etc/wsl.conf
```
```ini
[automount]
enabled = true
mountFsTab = true
```

Redémarrage WSL (depuis PowerShell) :
```powershell
wsl --shutdown
wsl
```

> **Note :** l'accès réseau dépend de l'authentification Windows (compte AD / VPN). Si WSL démarre hors réseau, le montage échouera silencieusement — le dashboard détecte ce cas et affiche un avertissement dans l'onglet Admin > Données.
>
> **Si `sudo mount -a` échoue au démarrage** : c'est que WSL a démarré avant que Windows soit connecté au réseau d'entreprise. Attendez que Windows soit bien connecté (session AD active, VPN si nécessaire), puis relancez simplement :
> ```bash
> sudo mount -a
> ```

---

## Notes personnelles

### Positions liquidées — explication de l'écart Δ VM

Le total Δ VM du tableau de détail par titre reflète uniquement l'évolution des positions encore détenues à la date de fin, tandis que les tableaux de concentration intègrent également l'impact des positions liquidées sur la période ; la ligne "Positions liquidées" a été ajoutée pour réconcilier les deux et garantir que le total affiché correspond bien à la variation nette du portefeuille.

**Différence de périmètre :**

Tableaux du haut :
```
Delta_total = Σ(VM à d1) − Σ(VM à d0)
```
Incluent toutes les positions de d0 et d1, y compris les titres liquidés (VM_FIN=0, VM_DEBUT=X → Delta=−X).

Tableau de détail :
```
Delta_total = Σ(VM_FIN) − Σ(VM_DEBUT des titres encore présents à d1)
```
Ne montre que les positions encore détenues à d1. Les titres vendus n'y apparaissent pas.

La différence = valeur de marché à d0 des positions liquidées entre d0 et d1.

---

### Valeurs rouges VaR 99%

Les cellules rouges dans la colonne VaR 99% correspondent aux titres dont la VaR 99% dépasse le **75e percentile** des titres affichés (hors lignes Autres et TOTAL). Seuil paramétrable via `var_quantile` dans la config admin (défaut : 0.75).

---

### VS Code — lignes rouges (interpréteur Python)

`Ctrl+Shift+P` → *Python: Select Interpreter* → sélectionner `./venv/bin/python3`
