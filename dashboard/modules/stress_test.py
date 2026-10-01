# dashboard/modules/stress_test.py
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# Configuration — adapter si l'environnement change
# =============================================================================

_SAS_EXE_WIN = r"C:\Program Files\SASHome\SASFoundation\9.4\sas.exe"
_SAS_PROG_WIN = (
    r"Y:\Direction des Risques\4. Risques Financiers"
    r"\00-1-TRAVAUX\2026 09 - 02 - Stress Tests Ptf"
    r"\Programme_SAS_Stress_Test.sas"
)
_PARAM_WIN   = r"C:\temp\param_run.txt"
_LOG_WIN     = r"C:\temp\logSAS.txt"
_RESULTS_WIN = r"C:\temp\stress_results"

# Colonnes disponibles pour le périmètre (types 3 & 4)
_PERIM_COLS = ["LIB_EMETTEUR", "SOUS_CLASSIF_RF", "PAYS", "SECTEUR_EPS"]

_TYPE_LABELS = {
    1: "1 – Stress taux",
    2: "2 – Stress BEI",
    3: "3 – Stress spread",
    4: "4 – Stress valorisation",
}

# =============================================================================
# Helpers — environnement et chemins
# =============================================================================

def _is_wsl() -> bool:
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except FileNotFoundError:
        return False


def _py_path(win_path: str) -> Path:
    """Convertit un chemin Windows vers un chemin Python lisible (WSL ou Windows natif)."""
    if _is_wsl():
        p = win_path.replace("\\", "/")
        if len(p) >= 2 and p[1] == ":":
            drive = p[0].lower()
            return Path(f"/mnt/{drive}{p[2:]}")
    return Path(win_path)


# =============================================================================
# Construction du fichier param_run.txt
# =============================================================================

def _build_perim(filters: dict[str, list[str]]) -> str:
    """Construit la clause WHERE SAS depuis les filtres de périmètre."""
    parts = []
    for col, vals in filters.items():
        if vals:
            quoted = ", ".join(f"'{v}'" for v in vals)
            parts.append(f"{col} in ({quoted})")
    return " and ".join(parts) if parts else "n.a."


def _build_param_content(scenarios: list[dict], date_sim: str) -> str:
    lines = [
        f"REP_JSON;{_RESULTS_WIN}",
        f"DATE_SIM;{date_sim}",
    ]
    for i, s in enumerate(scenarios, 1):
        t = s["type"]
        lines.append(f"TYPE_STRESS{i};{t}")
        if t in (1, 2):
            lines.append(f"PERIM_STRESS{i};n.a.")
            lines.append(f"VAL_STRESS{i}_1;{int(s.get('val1', 0))}")
            lines.append(f"VAL_STRESS{i}_2;{int(s.get('val2', 0))}")
        else:
            lines.append(f"PERIM_STRESS{i};{_build_perim(s.get('perim', {}))}")
            lines.append(f"VAL_STRESS{i};{s.get('val', 0)}")
    return "\n".join(lines)


def _write_param_file(scenarios: list[dict], date_sim: str) -> None:
    content = _build_param_content(scenarios, date_sim)
    param = _py_path(_PARAM_WIN)
    param.parent.mkdir(parents=True, exist_ok=True)
    param.write_text(content, encoding="utf-8")
    # Nettoie les anciens résultats avant chaque run
    res_dir = _py_path(_RESULTS_WIN)
    res_dir.mkdir(parents=True, exist_ok=True)
    for old in res_dir.glob("*.json"):
        old.unlink(missing_ok=True)


# =============================================================================
# Lancement SAS (non bloquant)
# =============================================================================

def _launch_sas() -> subprocess.Popen:
    sas_cmd = (
        f'"{_SAS_EXE_WIN}" '
        f'-sysin "{_SAS_PROG_WIN}" '
        f'-log "{_LOG_WIN}"'
    )
    if _is_wsl():
        return subprocess.Popen(
            ["cmd.exe", "/c", sas_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return subprocess.Popen(
        sas_cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# =============================================================================
# Lecture du log SAS
# =============================================================================

def _check_sas_log() -> tuple[list[str], list[str]]:
    """Retourne (erreurs, dernières_lignes) du log SAS."""
    log = _py_path(_LOG_WIN)
    if not log.exists():
        return [f"⚠️ Log SAS introuvable : {log}"], []
    errors = []
    all_lines = []
    try:
        with open(log, encoding="latin-1", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    all_lines.append(stripped)
                if stripped.startswith("ERROR") or "ERROR:" in stripped:
                    errors.append(stripped)
    except Exception as e:
        errors.append(f"Impossible de lire le log : {e}")
    tail = all_lines[-30:] if len(all_lines) > 30 else all_lines
    return errors, tail


# =============================================================================
# Chargement des JSON produits par SAS
# =============================================================================

def _load_stress_results() -> Optional[pd.DataFrame]:
    rdir = _py_path(_RESULTS_WIN)
    if not rdir.exists():
        return None
    files = sorted(rdir.glob("*.json"))
    if not files:
        return None
    dfs = []
    for f in files:
        try:
            df = pd.read_json(f)
            df["_scenario"] = f.stem
            dfs.append(df)
        except Exception:
            pass
    return pd.concat(dfs, ignore_index=True) if dfs else None


# =============================================================================
# UI — formulaire d'un scénario
# =============================================================================

def _render_scenario_form(idx: int, scenario: dict, df_selection: pd.DataFrame) -> Optional[dict]:
    """
    Affiche le formulaire d'édition d'un scénario dans un expander.
    Retourne le dict mis à jour, ou None si l'utilisateur a cliqué sur Supprimer.
    """
    t_current = scenario.get("type", 1)
    label = f"Scénario {idx} — {_TYPE_LABELS.get(t_current, '')}"

    with st.expander(label, expanded=True):
        col_type, col_del = st.columns([5, 1])

        with col_type:
            t = st.selectbox(
                "Type de stress",
                options=list(_TYPE_LABELS.keys()),
                format_func=lambda x: _TYPE_LABELS[x],
                index=list(_TYPE_LABELS.keys()).index(t_current),
                key=f"sc_{idx}_type",
            )
        with col_del:
            st.markdown("<div style='margin-top:27px'>", unsafe_allow_html=True)
            delete = st.button("🗑", key=f"sc_{idx}_del", help="Supprimer ce scénario")
            st.markdown("</div>", unsafe_allow_html=True)

        if delete:
            return None

        scenario["type"] = t

        # ── Types 1 & 2 : périmètre n.a., 2 valeurs ──
        if t in (1, 2):
            st.caption("Périmètre : **n.a.** — appliqué à l'ensemble du portefeuille")
            scenario["perim"] = {}
            c1, c2 = st.columns(2)
            lbl1 = "ZCN 1 an (bp)"   if t == 1 else "BEI 1 an (bp)"
            lbl2 = "ZCN 10 ans (bp)" if t == 1 else "BEI 10 ans (bp)"
            with c1:
                scenario["val1"] = st.number_input(
                    lbl1, value=int(scenario.get("val1", 0)), step=1, key=f"sc_{idx}_val1",
                )
            with c2:
                scenario["val2"] = st.number_input(
                    lbl2, value=int(scenario.get("val2", 0)), step=1, key=f"sc_{idx}_val2",
                )

        # ── Types 3 & 4 : périmètre libre, 1 valeur ──
        else:
            st.markdown("**Périmètre** — sélection dans une ou plusieurs dimensions :")
            perim = scenario.get("perim", {})
            perim_cols_present = [c for c in _PERIM_COLS if c in df_selection.columns]
            grid = st.columns(max(len(perim_cols_present), 1))

            for ci, col in enumerate(perim_cols_present):
                opts = sorted(df_selection[col].dropna().astype(str).unique().tolist())
                current = [v for v in perim.get(col, []) if v in opts]
                with grid[ci]:
                    sel = st.multiselect(col, options=opts, default=current, key=f"sc_{idx}_perim_{col}")
                perim[col] = sel

            scenario["perim"] = {k: v for k, v in perim.items() if v}

            # Résumé texte du périmètre construit
            perim_str = _build_perim(scenario["perim"])
            if perim_str != "n.a.":
                st.caption(f"Clause SAS : `{perim_str}`")

            if t == 3:
                scenario["val"] = st.number_input(
                    "Spread (bp)",
                    value=float(scenario.get("val", 0)),
                    step=1.0,
                    key=f"sc_{idx}_val",
                )
            else:
                scenario["val"] = st.number_input(
                    "Valorisation (%)",
                    value=float(scenario.get("val", 0)),
                    step=0.5,
                    key=f"sc_{idx}_val",
                )

    return scenario


# =============================================================================
# Affichage des résultats
# =============================================================================

def _render_stress_results(
    df_base: pd.DataFrame,
    df_stressed: pd.DataFrame,
    date_sim: str,
) -> None:
    DATE_COL     = "DATE_TRANSPA"
    VM_COL       = "VM_INIT"
    CLASS_COL    = "CLASSIF_RF"
    SUBCLASS_COL = "SOUS_CLASSIF_RF"

    # VM de base à la date de simulation
    df_b = df_base.copy()
    df_b[DATE_COL] = pd.to_datetime(df_b[DATE_COL]).dt.date
    d_sim = pd.to_datetime(date_sim, dayfirst=True).date()
    d_eff = df_b.loc[df_b[DATE_COL] <= d_sim, DATE_COL].max()
    if pd.isna(d_eff):
        st.warning("Aucune donnée de base disponible à la date de simulation.")
        return
    df_b = df_b[df_b[DATE_COL] == d_eff]

    vm_base_total = df_b[VM_COL].sum() / 1e6 if VM_COL in df_b.columns else 0.0

    scenarios_in_results = (
        df_stressed["_scenario"].unique()
        if "_scenario" in df_stressed.columns
        else ["stress"]
    )

    for sc_name in scenarios_in_results:
        df_sc = (
            df_stressed[df_stressed["_scenario"] == sc_name]
            if "_scenario" in df_stressed.columns
            else df_stressed
        )

        vm_stress_total = df_sc[VM_COL].sum() / 1e6 if VM_COL in df_sc.columns else 0.0
        impact_total    = vm_stress_total - vm_base_total

        st.markdown(f"### 📋 {sc_name}")

        # ── KPIs ──
        k1, k2, k3 = st.columns(3)
        k1.metric("VM initiale (M€)",  f"{vm_base_total:,.1f}".replace(",", " "))
        k2.metric("VM stressée (M€)",  f"{vm_stress_total:,.1f}".replace(",", " "))
        k3.metric(
            "Impact (M€)",
            f"{impact_total:+,.1f}".replace(",", " "),
            delta=f"{impact_total / vm_base_total * 100:+.2f} %" if vm_base_total else None,
            delta_color="inverse",
        )

        # ── Graphe & tableau par classe d'actifs ──
        if CLASS_COL in df_b.columns and CLASS_COL in df_sc.columns:
            g_b  = df_b.groupby(CLASS_COL)[VM_COL].sum().rename("VM_base")
            g_s  = df_sc.groupby(CLASS_COL)[VM_COL].sum().rename("VM_stress")
            agg  = pd.concat([g_b, g_s], axis=1).fillna(0)
            agg["Impact (M€)"]      = (agg["VM_stress"] - agg["VM_base"]) / 1e6
            agg["VM initiale (M€)"] = agg["VM_base"]  / 1e6
            agg["VM stressée (M€)"] = agg["VM_stress"] / 1e6
            agg = agg.drop(columns=["VM_base", "VM_stress"]).reset_index()
            agg = agg.rename(columns={CLASS_COL: "Classe d'actifs"})
            agg = agg.sort_values("Impact (M€)")

            fig = go.Figure(go.Bar(
                x=agg["Classe d'actifs"],
                y=agg["Impact (M€)"],
                marker_color=[
                    "#d62728" if v < 0 else "#2ca02c" for v in agg["Impact (M€)"]
                ],
                text=[f"{v:+.1f} M€" for v in agg["Impact (M€)"]],
                textposition="outside",
            ))
            fig.update_layout(
                title="Impact par classe d'actifs (M€)",
                height=320,
                margin=dict(l=20, r=20, t=50, b=60),
                yaxis_title="M€",
                xaxis_tickangle=-20,
            )
            st.plotly_chart(fig, use_container_width=True, key=f"stress_bar_{sc_name}")

            st.dataframe(
                agg.style.format({
                    "VM initiale (M€)":  "{:,.1f}",
                    "VM stressée (M€)":  "{:,.1f}",
                    "Impact (M€)":       "{:+,.1f}",
                }),
                use_container_width=True,
            )

        st.markdown("---")


# =============================================================================
# Point d'entrée — appelé depuis home.py
# =============================================================================

def render_stress_tab(df_selection: pd.DataFrame, date_fin) -> None:
    st.subheader("Stress Tests")
    date_sim_str = pd.to_datetime(date_fin).strftime("%d/%m/%Y")
    st.caption(f"Date de simulation : **{date_sim_str}**")
    st.markdown("---")

    # ── Init session state ──
    if "stress_scenarios" not in st.session_state:
        st.session_state["stress_scenarios"] = [{"type": 1, "val1": 0, "val2": 0, "perim": {}}]
    if "sas_status" not in st.session_state:
        st.session_state["sas_status"] = "idle"

    # ── Formulaires des scénarios ──
    scenarios: list[dict] = st.session_state["stress_scenarios"]
    to_remove = []
    for i, sc in enumerate(scenarios):
        result = _render_scenario_form(i + 1, sc, df_selection)
        if result is None:
            to_remove.append(i)
        else:
            scenarios[i] = result

    for idx in sorted(to_remove, reverse=True):
        scenarios.pop(idx)
    st.session_state["stress_scenarios"] = scenarios

    # ── Boutons ──
    st.markdown("")
    col_add, col_run, _ = st.columns([1, 1, 2])
    with col_add:
        if st.button("➕ Ajouter un scénario", use_container_width=True):
            st.session_state["stress_scenarios"].append(
                {"type": 1, "val1": 0, "val2": 0, "perim": {}}
            )
            st.rerun()
    with col_run:
        if st.button(
            "▶ Lancer les scénarios",
            disabled=not scenarios,
            type="primary",
            use_container_width=True,
        ):
            _write_param_file(scenarios, date_sim_str)
            proc = _launch_sas()
            st.session_state["sas_process"] = proc
            st.session_state["sas_status"]  = "running"
            st.session_state["sas_start"]   = time.time()
            st.rerun()

    # ── Suivi de l'exécution SAS ──
    status = st.session_state.get("sas_status", "idle")

    if status == "running":
        proc    = st.session_state.get("sas_process")
        elapsed = int(time.time() - st.session_state.get("sas_start", time.time()))
        st.info(f"⏳ SAS en cours d'exécution… ({elapsed} s)")
        if proc is not None and proc.poll() is None:
            time.sleep(2)
            st.rerun()
        else:
            rc = proc.returncode if proc else -1
            errors, tail = _check_sas_log()
            # SAS retourne code 1 en cas de warnings : on vérifie la présence du JSON
            results_exist = bool(
                list(_py_path(_RESULTS_WIN).glob("*.json"))
            ) if _py_path(_RESULTS_WIN).exists() else False
            if not errors and results_exist:
                # Succès réel : JSON produit, aucune ligne ERROR dans le log
                st.session_state["sas_status"] = "done"
                st.session_state["sas_rc"] = rc
                st.session_state["sas_errors"] = []
                st.session_state["sas_log_tail"] = []
            else:
                st.session_state["sas_status"] = "error"
                st.session_state["sas_rc"] = rc
                st.session_state["sas_errors"] = errors
                st.session_state["sas_log_tail"] = tail
            st.rerun()

    elif status == "error":
        rc_val    = st.session_state.get("sas_rc", -1)
        err_lines = st.session_state.get("sas_errors", [])
        tail_lines = st.session_state.get("sas_log_tail", [])

        st.error(f"❌ Erreur lors de l'exécution SAS (code retour : {rc_val})")

        if err_lines:
            st.markdown("**Lignes ERROR détectées dans le log :**")
            for e in err_lines[:20]:
                st.code(e, language=None)

        if tail_lines:
            label = "📋 Fin du log SAS" if not err_lines else "📋 Fin du log SAS (contexte)"
            with st.expander(label, expanded=not err_lines):
                st.code("\n".join(tail_lines), language=None)
        elif not err_lines:
            st.warning(
                f"Log SAS introuvable ou vide (`{_py_path(_LOG_WIN)}`). "
                "Vérifiez que SAS peut écrire dans `C:\\\\temp\\\\`."
            )

        # Affiche le param_run.txt écrit
        param_path = _py_path(_PARAM_WIN)
        if param_path.exists():
            with st.expander("📄 Contenu de param_run.txt (debug)"):
                st.code(param_path.read_text(encoding="utf-8"), language=None)

        if st.button("🔄 Réinitialiser"):
            st.session_state["sas_status"] = "idle"
            st.rerun()

    elif status == "done":
        elapsed = int(time.time() - st.session_state.get("sas_start", time.time()))
        st.success(f"✅ SAS terminé ({elapsed} s)")

        df_stressed = _load_stress_results()
        if df_stressed is not None and not df_stressed.empty:
            _render_stress_results(df_selection, df_stressed, date_sim_str)
        else:
            st.warning(
                f"Aucun fichier JSON trouvé dans `{_RESULTS_WIN}`. "
                "Vérifiez que SAS a bien produit des fichiers de sortie."
            )

        if st.button("🔄 Nouveau stress test"):
            st.session_state["sas_status"] = "idle"
            st.rerun()
