# Etape de lancement du programme

1 - Se mettre dans le dossier dashboard
cd dashboard/

2 - Activer la variable d'envvironnement
source ~/venvs/jupyter/bin/activate

3- Lancer le programme
streamlit run home.py

---

## MàJ des données — Montage du répertoire réseau

### Montage manuel (ponctuel)

À la racine du projet :

```bash
cd /mnt
```

Vérifier si le dossier `risques` existe, sinon le créer :

```bash
ls -lrt
sudo mkdir risques
```

Monter le partage réseau :

```bash
sudo mount -t drvfs '\\sv61file0024\Bureautique\Direction des Risques\' /mnt/risques
```

Vérifier le répertoire monté :

```bash
ls -la "/mnt/risques/4. Risques Financiers/00-0-REPORTING/01 - HISTO SAS/0000T0"
```

---

### Montage automatique au démarrage WSL (configuration permanente)

Évite de retaper le mot de passe sudo à chaque session.

**Étape 1 — Créer le point de montage**

```bash
sudo mkdir -p /mnt/risques
```

**Étape 2 — Activer fstab dans WSL2**

```bash
sudo nano /etc/wsl.conf
```

Ajouter ou compléter avec :

```ini
[automount]
enabled = true
mountFsTab = true
```

**Étape 3 — Ajouter l'entrée dans `/etc/fstab`**

```bash
sudo nano /etc/fstab
```

Ajouter cette ligne (les espaces du chemin s'écrivent `\040`) :

```
\\sv61file0024\Bureautique\Direction\040des\040Risques  /mnt/risques  drvfs  defaults,metadata  0  0
```

**Étape 4 — Tester sans redémarrer**

```bash
sudo mount -a
ls /mnt/risques
```

Si la commande retourne sans erreur et que les fichiers sont visibles, le montage fonctionne.

**Étape 5 — Rendre permanent (redémarrage WSL)**

Depuis PowerShell Windows :

```powershell
wsl --shutdown
wsl
```

Après redémarrage, `/mnt/risques` est monté automatiquement sans demande de mot de passe.

> **Note :** l'accès réseau dépend de l'authentification Windows (compte AD / VPN). Si WSL démarre hors réseau, le montage échouera silencieusement — le dashboard détecte ce cas et affiche un avertissement dans l'onglet Admin > Données.

Exécuter le fichier

# Etape de lancement du programme

si nécessaire (pour recréer les variables d'environnement puis les activer)
python -m venv .venvs
.\.venvs\Scripts\Activate.ps1

puis, depuis le répertoire risk_dashboard
pip install -r requirements.txt

1 - Se mettre dans le dossier dashboard
cd dashboard/

2 - Activer la variable d'envvironnement
source ~/venvs/jupyter/bin/activate

3- Lancer le programme
streamlit run home.py --server.address 0.0.0.0 --server.headless true

======================================================
avec le cmd
======================================================

# OBJECTIF

Utiliser **CMD (invite de commande)**
Créer un **venv propre**
Voir `(.venv)` quand il est activé
Installer et lancer ton projet

---

# ÉTAPES COMPLÈTES

## 1. Ouvrir CMD (pas PowerShell)

Méthode rapide :

- Appuie sur `Win + R`
- Tape : cmd

- Appuie sur Entrée

---

## 2. Aller dans ton projet

cd C:\Users\ghisl\Desktop\risk_dashboard

---

## 3. Supprimer les anciens environnements (optionnel mais conseillé)

rmdir /s /q dashboard\.venvs
rmdir /s /q .venv

---

## 4. Créer un nouvel environnement avec Python 3.11

py -3.11 -m venv .venv

---

## 5. Activer le venv (ICI tu verras (.venv))

.venv\Scripts\activate.bat

Résultat attendu :
(.venv) C:\Users\ghisl\Desktop\risk_dashboard>

---

## 6. Installer les dépendances

python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

---

## 7. Lancer ton app Streamlit

streamlit run dashboard\home.py

---

# RÉSUMÉ ULTRA COURT

cmd
cd C:\Users\ghisl\Desktop\risk_dashboard
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
streamlit run dashboard\home.py

---

# RÉSULTAT FINAL

- `(.venv)` visible
- dépendances installées
- app Streamlit qui tourne
- plus de bug numpy

---

# RÈGLES IMPORTANTES

- Toujours utiliser **CMD pour voir (.venv)**
- Ne pas mélanger avec PowerShell
- Toujours lancer le projet depuis la racine `risk_dashboard`

================================================================
WSL
================================================================

# OBJECTIF (WSL)

- utiliser Linux (WSL)
- créer un venv propre
- voir `(.venv)`
- installer les dépendances
- lancer Streamlit

---

# ÉTAPES COMPLÈTES (WSL)

## 1. Ouvrir WSL (Ubuntu)

soit via terminal :

```bash
wsl
```

- soit via menu :

* ouvrir **Ubuntu**

---

## 2. Aller dans ton projet

Notre projet est sur Windows, donc accessible via `/mnt/c/`

cd /mnt/c/Users/ghisl/Desktop/risk_dashboard

---

## 3. Supprimer anciens environnements

rm -rf dashboard/.venvs
rm -rf .venv

---

## 4. Vérifier Python

python3 --version

idéalement Python 3.11

---

## 5. Installer venv (si besoin)

sudo apt update
sudo apt install python3-venv -y

---

## 6. Créer le venv

python3 -m venv .venv

---

## 7. Activer le venv (ICI tu verras (.venv))

source .venv/bin/activate

Résultat attendu :

(.venv) user@machine:/mnt/c/Users/ghisl/Desktop/risk_dashboard$

---

## 8. Installer les dépendances

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

---

## 9. Lancer ton app Streamlit

streamlit run dashboard/home.py

---

# RÉSUMÉ ULTRA COURT (WSL)

wsl
cd /mnt/c/Users/ghisl/Desktop/risk_dashboard
rm -rf .venv dashboard/.venvs
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run dashboard/home.py

---

# RÉSULTAT FINAL

- `(.venv)` visible
- installation propre
- pas de problème Windows/PowerShell
- moins de bugs numpy

---

# POINTS IMPORTANTS

- chemins Windows → `/mnt/c/...`
- toujours utiliser `python3` (pas `python`)
- activer avec `source`, pas `.bat`

---

# (important)

Si `streamlit` n’est pas trouvé :

```bash
pip install streamlit
```

---

WSL est **meilleur que Windows** pour Python :

- moins de bugs de compilation
- pas de problème Visual C++
- environnement plus stable







# 1 explication positions liquidées
Le total Δ VM du tableau de détail par titre reflète uniquement l'évolution des positions encore détenues à la date de fin, tandis que les tableaux de concentration intègrent également l'impact des positions liquidées sur la période ; la ligne "Positions liquidées" a été ajoutée pour réconcilier les deux et garantir que le total affiché correspond bien à la variation nette du portefeuille.

# 2
Ce n'est pas un bug — c'est une différence de périmètre.

Tableaux du haut (−34,7 M€) :


Delta_total = Σ(VM à d1) − Σ(VM à d0)
Ils incluent toutes les positions de d0 et d1, y compris les titres liquidés entre les deux dates (VM_FIN=0, VM_DEBUT=X → Delta=−X).

Tableau de détail (−22,5 M€) :


Delta_total = Σ(VM_FIN) − Σ(VM_DEBUT des titres encore présents à d1)
Il ne montre que les positions encore détenues à d1. Les titres vendus n'y apparaissent pas.

La différence : 34,7 − 22,5 = 12,2 M€ = valeur de marché à d0 des positions liquidées entre d0 et d1. Ces positions tirent le delta du portefeuille vers le bas dans les tableaux du haut, mais sont absentes du tableau de détail.



===============================================
Pour appliquer le changement : dans VS Code, appuie sur Ctrl+Shift+P → "Python: Select Interpreter" → sélectionne le venv (./venv/bin/python3). Les lignes rouges devraient disparaître.