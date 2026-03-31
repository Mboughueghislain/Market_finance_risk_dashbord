# Etape de lancement du programme

1 - Se mettre dans le dossier dashboard
cd dashboard/

2 - Activer la variable d'envvironnement
source ~/venvs/jupyter/bin/activate

3- Lancer le programme
streamlit run home.py

---

## MàJ des données, monter d'abord le repertoire

sudo mount -t drvfs '\\sv61file0024\Bureautique\Direction des Risques\' /mnt/risques

Verifier le repertoire monté
ls -la "/mnt/risques/4. Risques Financiers/00-0-REPORTING/01 - HISTO SAS/0000T0"

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
streamlit run home.py

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
