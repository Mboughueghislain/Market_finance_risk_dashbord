# data/app_config.py
"""
Gestion de la configuration persistante de l'application.
Les paramètres sont stockés dans app_config.json (même dossier).
Mots de passe hashés avec bcrypt (compatible streamlit-authenticator).
"""

import json
import bcrypt
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "app_config.json"

ROLES = ["Lecteur", "Analyste", "Admin"]


def _hash(password: str) -> str:
    """Retourne le hash bcrypt du mot de passe (compatible streamlit-authenticator)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    """Vérifie un mot de passe contre son hash bcrypt."""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


DEFAULTS: dict = {
    "source_dir": "/mnt/risques/4. Risques Financiers/00-0-REPORTING/01 - HISTO SAS/0000T0",
    "suivi_risques_picture_dir": "\\\\sv61file0024\\Bureautique\\Direction des Risques\\4. Risques Financiers\\00-0-REPORTING\\00 - PROD RRF\\Suivi Risques\\PICTURE",
    "suivi_risques_archives_dir": "\\\\sv61file0024\\Bureautique\\Direction des Risques\\4. Risques Financiers\\00-0-REPORTING\\00 - PROD RRF\\Suivi Risques\\ARCHIVES",
    "var_quantile": 0.75,
    "default_top_n": 20,
    "backup_enabled": False,
    "backup_keep": 5,
    "cookie_key": "risk_dashboard_secret_key_change_me",
    "users": [
        {
            "username": "admin",
            "role": "Admin",
            "active": True,
            "password_hash": _hash("admin1234"),
        }
    ],
}


def load_config() -> dict:
    """Charge la config depuis le fichier JSON, complète avec les valeurs par défaut."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # Fusion : les valeurs du fichier écrasent les defaults,
            # sauf pour 'users' qui doit être présent dans le fichier pour être utilisé.
            merged = {**DEFAULTS, **data}
            if "users" not in data:
                merged["users"] = DEFAULTS["users"]
            return merged
        except Exception:
            pass
    return DEFAULTS.copy()


def save_config(cfg: dict) -> None:
    """Sauvegarde la config dans le fichier JSON."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── Helpers utilisateurs ──────────────────────────────────────────────────────

def get_users(cfg: dict) -> list[dict]:
    return cfg.get("users", DEFAULTS["users"])


def find_user(cfg: dict, username: str) -> dict | None:
    # Comparaison insensible à la casse — stauth normalise les usernames en minuscules
    _u = username.lower().strip()
    return next((u for u in get_users(cfg) if u["username"].lower() == _u), None)


def add_user(cfg: dict, username: str, role: str, password: str) -> str | None:
    """Ajoute un utilisateur. Retourne un message d'erreur ou None si OK."""
    username = username.strip().lower()   # aligné sur la normalisation stauth
    if not username:
        return "Le nom d'utilisateur ne peut pas être vide."
    if find_user(cfg, username):
        return f"L'utilisateur « {username} » existe déjà."
    if role not in ROLES:
        return f"Rôle invalide : {role}."
    if len(password) < 6:
        return "Le mot de passe doit comporter au moins 6 caractères."
    cfg.setdefault("users", []).append({
        "username": username,
        "role": role,
        "active": True,
        "password_hash": _hash(password),
    })
    return None


def set_user_active(cfg: dict, username: str, active: bool) -> None:
    user = find_user(cfg, username)
    if user:
        user["active"] = active


def delete_user(cfg: dict, username: str) -> str | None:
    """Supprime un utilisateur. Retourne un message d'erreur ou None si OK."""
    _u = username.lower().strip()
    if _u == "admin":
        return "L'utilisateur admin principal ne peut pas être supprimé."
    users = get_users(cfg)
    new_users = [u for u in users if u["username"].lower() != _u]
    if len(new_users) == len(users):
        return f"Utilisateur « {username} » introuvable."
    cfg["users"] = new_users
    return None


def update_password(cfg: dict, username: str, new_password: str) -> str | None:
    """Change le mot de passe d'un utilisateur. Retourne un message d'erreur ou None."""
    if len(new_password) < 6:
        return "Le mot de passe doit comporter au moins 6 caractères."
    user = find_user(cfg, username)
    if not user:
        return f"Utilisateur « {username} » introuvable."
    user["password_hash"] = _hash(new_password)
    return None
