# dashboard/modules/stress_test.py
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

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
# Répertoire réel où SAS écrit ses JSON — chemin UNC (Y: non disponible depuis WSL2)
_RESULTS_WIN = (
    r"\\sv61file0024\Bureautique\Direction des Risques\4. Risques Financiers"
    r"\00-0-REPORTING\00 - PROD RRF\outSAS\Json"
)
_STRESS_JSON_NAME = "STRESS_TEST.json"

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
    # Le répertoire de résultats est sur partage réseau : pas de nettoyage
    # SAS écrase automatiquement STRESS_TEST.json à chaque run


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

def _stress_json_exists_win() -> bool:
    """Vérifie l'existence du STRESS_TEST.json via PowerShell (accès réseau avec credentials)."""
    win_path = f"{_RESULTS_WIN}\\{_STRESS_JSON_NAME}"
    try:
        r = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-Command",
             f"Test-Path '{win_path}'"],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip().lower() == "true"
    except Exception:
        return False


def _read_json_via_ps(win_path: str) -> Optional[str]:
    """Lit le contenu d'un fichier via PowerShell (fonctionne sur partage réseau)."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-Command",
             f"Get-Content -Path '{win_path}' -Raw -Encoding UTF8"],
            capture_output=True, timeout=60,
        )
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def _load_stress_results() -> Optional[pd.DataFrame]:
    win_path = f"{_RESULTS_WIN}\\{_STRESS_JSON_NAME}"
    content = _read_json_via_ps(win_path)
    if not content:
        return None
    try:
        import io
        df = pd.read_json(io.StringIO(content))
        df["_scenario"] = _STRESS_JSON_NAME.replace(".json", "")
        return df
    except Exception:
        return None


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

def _fmt_num(val, signed: bool = False, pct: bool = False) -> str:
    if not isinstance(val, (int, float)) or pd.isna(val):
        return "—"
    if pct:
        s = f"{val:+.2f} %" if signed else f"{val:.2f} %"
    else:
        s = f"{val:+,.1f}" if signed else f"{val:,.1f}"
        s = s.replace(",", " ")
    return s


def _td(val, signed: bool = False, pct: bool = False) -> str:
    txt = _fmt_num(val, signed, pct)
    if not isinstance(val, (int, float)) or pd.isna(val) or val == 0:
        return f'<td class="n">{txt}</td>'
    cls = "neg" if val < 0 else "pos"
    return f'<td class="n {cls}">{txt}</td>'


def _render_stress_html_table(df_j: pd.DataFrame, levels: list[str], sc_name: str) -> None:
    """Génère et affiche un tableau HTML stylé hiérarchique Canton→Classe→Sous-classe."""
    present = [c for c in levels if c in df_j.columns]
    if not present:
        st.info("Aucune colonne de regroupement disponible.")
        return

    AGG = dict(
        vm_i=("VM_INIT",     "sum"), vm_s=("VM_stress",   "sum"),
        pl=  ("PDD_latente", "sum"), ps=  ("PDD_simulee",  "sum"),
        ml=  ("PV_mob",      "sum"), ms=  ("PV_mob_sim",   "sum"),
    )
    S = 1e6

    def _pct(num, denom):
        return (num / denom * 100) if denom and abs(denom) > 1e-9 else float("nan")

    def _row_vals(g):
        vm_i, vm_s = g["VM_INIT"].sum()/S, g["VM_stress"].sum()/S
        pl,   ps   = g["PDD_latente"].sum()/S, g["PDD_simulee"].sum()/S
        ml,   ms   = g["PV_mob"].sum()/S,  g["PV_mob_sim"].sum()/S
        d_vm  = vm_s - vm_i;  d_pl = ps - pl;  d_ml = ms - ml
        return (vm_i, vm_s, d_vm, _pct(d_vm, vm_i),
                pl, ps, d_pl, _pct(d_pl, pl),
                ml, ms, d_ml, _pct(d_ml, ml))

    CSS = """
    <style>
      .st-wrap{overflow-x:auto;border-radius:8px;
               box-shadow:0 2px 10px rgba(113,74,128,.20);margin-bottom:16px}
      .st-tbl{border-collapse:collapse;width:100%;
              font-family:'Segoe UI',Arial,sans-serif;font-size:12.5px}
      /* ── Header ── */
      .st-tbl thead tr th{
        background:#714A80;color:#fff;padding:9px 12px;
        white-space:nowrap;border:none;font-weight:600;letter-spacing:.3px
      }
      .st-tbl thead tr th.lbl{text-align:left}
      .st-tbl thead tr th.n{text-align:right}
      /* ── Canton ── */
      .r0 td{background:#4e3059;color:#fff;font-weight:700;
             padding:8px 12px;border-bottom:2px solid #3d2447}
      /* ── Classe ── */
      .r1 td{background:#e8d9f0;color:#1a1a2e;font-weight:600;
             padding:7px 12px;border-bottom:1px solid #c4a8d4}
      /* ── Sous-classe ── */
      .r2 td{background:#f5f0fa;color:#1a1a2e;
             padding:5px 12px;border-bottom:1px solid #e0d4ea}
      .r2:hover td{background:#ede4f5}
      /* ── Numérique ── */
      .n{text-align:right!important}
      .neg{color:#d62728;font-weight:700}
      .pos{color:#2ca02c;font-weight:700}
      /* ── Indentation libellés ── */
      .lbl-0{padding-left:12px!important}
      .lbl-1{padding-left:26px!important}
      .lbl-2{padding-left:44px!important}
    </style>
    """

    HDR_LABELS = [
        ("VM init. (M€)",    False, False), ("VM stress. (M€)", False, False),
        ("Impact VM (M€)",   True,  False), ("Impact VM (%)",   True,  True),
        ("PDD lat. (M€)",    False, False), ("PDD sim. (M€)",   False, False),
        ("Δ PDD (M€)",       True,  False), ("Δ PDD (%)",        True,  True),
        ("PV mob (M€)",      False, False), ("PV mob sim. (M€)", False, False),
        ("Δ PV mob (M€)",    True,  False), ("Δ PV mob (%)",     True,  True),
    ]

    def _header_row() -> str:
        ths = "".join(f'<th class="lbl">{c}</th>' for c in present)
        ths += "".join(f'<th class="n">{h}</th>' for h, _ in HDR_LABELS)
        return f"<thead><tr>{ths}</tr></thead>"

    def _data_row(level: int, labels: list, vals: tuple) -> str:
        lbl_cls = f"lbl-{level}"
        tds = ""
        for i, lbl in enumerate(labels):
            indent = lbl_cls if i == level else ""
            tds += f'<td class="{indent}">{lbl}</td>'
        tds += "".join(_td(v, h[1], h[2]) for v, h in zip(vals, HDR_LABELS))
        return f'<tr class="r{level}">{tds}</tr>'

    body = "<tbody>"
    n = len(present)

    for canton, g0 in df_j.groupby(present[0], dropna=False, sort=True):
        v0 = _row_vals(g0)
        lbls0 = [str(canton)] + [""] * (n - 1)
        body += _data_row(0, lbls0, v0)

        if n > 1:
            for classe, g1 in g0.groupby(present[1], dropna=False, sort=True):
                v1 = _row_vals(g1)
                lbls1 = ["", str(classe)] + [""] * (n - 2)
                body += _data_row(1, lbls1, v1)

                if n > 2:
                    for sc_val, g2 in g1.groupby(present[2], dropna=False, sort=True):
                        v2 = _row_vals(g2)
                        lbls2 = ["", "", str(sc_val)]
                        body += _data_row(2, lbls2, v2)

    body += "</tbody>"
    html = f'{CSS}<div class="st-wrap"><table class="st-tbl">{_header_row()}{body}</table></div>'
    components.html(html, height=min(52 * (len(df_j) + 10), 650), scrolling=True)


def _bar_impact(df: pd.DataFrame, group_col: str, title: str, key: str) -> None:
    agg = (
        df.groupby(group_col, dropna=False)
        .agg(vi=("VM_INIT", "sum"), vs=("VM_stress", "sum"))
        .reset_index()
    )
    agg["impact"] = (agg["vs"] - agg["vi"]) / 1e6
    agg = agg.sort_values("impact")
    fig = go.Figure(go.Bar(
        x=agg[group_col].astype(str),
        y=agg["impact"],
        marker_color=["#dc2626" if v < 0 else "#16a34a" for v in agg["impact"]],
        text=[f"{v:+.1f}" for v in agg["impact"]],
        textposition="outside",
    ))
    fig.update_layout(
        title=title, height=300,
        margin=dict(l=20, r=20, t=50, b=60),
        yaxis_title="M€", xaxis_tickangle=-20,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


def _render_stress_results(
    df_base: pd.DataFrame,
    df_stressed: pd.DataFrame,
    date_sim: str,
) -> None:
    DATE_COL   = "DATE_TRANSPA"
    VM_COL     = "VM_INIT"
    VNC_COL    = "VNC"
    PDD_COL    = "RSQ_CPTA_PDD"
    CLASS_COL  = "CLASSIF_RF"
    SCLASS_COL = "SOUS_CLASSIF_RF"
    CANTON_COL = "CANTON"

    # ── Filtrage base à la date de simulation ──
    df_b = df_base.copy()
    df_b[DATE_COL] = pd.to_datetime(df_b[DATE_COL]).dt.date
    d_sim = pd.to_datetime(date_sim, dayfirst=True).date()
    d_eff = df_b.loc[df_b[DATE_COL] <= d_sim, DATE_COL].max()
    if pd.isna(d_eff):
        st.warning("Aucune donnée de base disponible à la date de simulation.")
        return
    df_b = df_b[df_b[DATE_COL] == d_eff]

    if VM_COL not in df_b.columns:
        st.error(f"Colonne '{VM_COL}' introuvable dans le portefeuille.")
        return

    scenarios = (
        df_stressed["_scenario"].unique()
        if "_scenario" in df_stressed.columns
        else ["stress"]
    )

    for sc_name in scenarios:
        df_sc = (
            df_stressed[df_stressed["_scenario"] == sc_name]
            if "_scenario" in df_stressed.columns
            else df_stressed
        )

        # ── Jointure sur ID : application du facteur prix_sim ──
        ps = pd.to_numeric(df_sc.get("prix_sim", pd.Series(dtype=float)), errors="coerce")
        sc_map = df_sc.assign(prix_sim=ps).set_index("ID")["prix_sim"] if "ID" in df_sc.columns else pd.Series(dtype=float)

        df_j = df_b.copy()
        df_j["prix_sim"]  = df_j["ID"].map(sc_map).fillna(1.0) if "ID" in df_j.columns else 1.0
        df_j["VM_stress"] = df_j[VM_COL] * df_j["prix_sim"]

        # ── PDD latente (existante) & simulée ──
        if VNC_COL in df_j.columns:
            vnc = pd.to_numeric(df_j[VNC_COL], errors="coerce").fillna(0)
            df_j["PDD_latente"] = (
                pd.to_numeric(df_j[PDD_COL], errors="coerce").fillna(0)
                if PDD_COL in df_j.columns
                else (vnc - pd.to_numeric(df_j[VM_COL], errors="coerce")).clip(lower=0)
            )
            df_j["PDD_simulee"] = (vnc - df_j["VM_stress"]).clip(lower=0)
            vm_num = pd.to_numeric(df_j[VM_COL], errors="coerce").fillna(0)
            df_j["PV_mob"]     = vm_num - vnc
            df_j["PV_mob_sim"] = df_j["VM_stress"] - vnc
        else:
            for col in ("PDD_latente", "PDD_simulee", "PV_mob", "PV_mob_sim"):
                df_j[col] = (
                    pd.to_numeric(df_j[PDD_COL], errors="coerce").fillna(0)
                    if col == "PDD_latente" and PDD_COL in df_j.columns
                    else 0.0
                )

        # ── Totaux ──
        s = 1e6
        vm_b  = df_j[VM_COL].sum() / s
        vm_st = df_j["VM_stress"].sum() / s
        imp   = vm_st - vm_b
        pdd_l = df_j["PDD_latente"].sum() / s
        pdd_s = df_j["PDD_simulee"].sum() / s
        pv    = df_j["PV_mob"].sum() / s
        pv_s  = df_j["PV_mob_sim"].sum() / s

        st.markdown(f"### 📋 {sc_name}")

        # ── KPIs globaux ──
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("VM initiale (M€)",  f"{vm_b:,.1f}".replace(",", " "))
        c2.metric(
            "VM stressée (M€)", f"{vm_st:,.1f}".replace(",", " "),
            delta=f"{imp:+,.1f} M€ ({imp/vm_b*100:+.2f} %)".replace(",", " ") if vm_b else None,
            delta_color="inverse",
        )
        c3.metric(
            "PDD latente (M€)", f"{pdd_l:,.1f}".replace(",", " "),
        )
        c4.metric(
            "PDD simulée (M€)", f"{pdd_s:,.1f}".replace(",", " "),
            delta=f"{pdd_s-pdd_l:+,.1f} M€".replace(",", " "),
            delta_color="inverse",
        )
        c5.metric(
            "PV mob (M€)", f"{pv:,.1f}".replace(",", " "),
            delta=f"{pv_s-pv:+,.1f} M€".replace(",", " "),
            delta_color="inverse",
        )

        # ── Graphique par classe d'actifs ──
        if CLASS_COL in df_j.columns:
            _bar_impact(df_j, CLASS_COL,
                        "Impact VM par classe d'actifs (M€)", f"bar_{sc_name}")

        # ── Tableau hiérarchique Canton → Classe → Sous-classe ──
        _render_stress_html_table(df_j, [CANTON_COL, CLASS_COL, SCLASS_COL], sc_name)

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
            # Via cmd.exe pour accéder au partage réseau (Y:) sans passer par WSL
            results_exist = _stress_json_exists_win()
            st.session_state["sas_debug"] = {
                "rc": rc,
                "results_path": f"{_RESULTS_WIN}\\{_STRESS_JSON_NAME}",
                "json_found": results_exist,
            }
            if not errors and results_exist:
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
        dbg = st.session_state.get("sas_debug", {})
        if dbg:
            with st.expander("🔍 Debug chemin résultats"):
                st.json(dbg)

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
