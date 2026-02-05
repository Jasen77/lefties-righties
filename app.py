# -*- coding: utf-8 -*-
import json
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

APP_NAME = "Lefties & Righties"
APP_VERSION = "0.2.6"
APP_CREATED = "05.02.2026"

DATA_FILE = "GolfData.xlsx"
STYLES_FILE = "styles.css"

st.set_page_config(page_title=APP_NAME, layout="wide")

# -- Načítanie vlastných štýlov (styles.css)
if Path(STYLES_FILE).exists():
    try:
        css = Path(STYLES_FILE).read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except Exception:
        pass

# -- Dodatočné štýly: aktívne triediace tlačidlo = tučné + väčšie písmo
st.markdown(
    """
<style>
/***** marker pred tlačidlom *****/
.marker { display:block; height:0; margin:0; padding:0; }
/***** Aktívne triediace tlačidlo (robustné selektory) *****/
.marker.sort-active + div[data-testid="stButton"] > button,
.marker.sort-active + div[data-testid="stButton"] button,
.marker.sort-active + div [data-testid="baseButton-secondary"],
.marker.sort-active + div button {
  font-weight: 700 !important;
  font-size: 1.05rem !important; /* zladené s tabuľkou */
}
</style>
""",
    unsafe_allow_html=True,
)

# -- Sticky hlavička (2 riadky) + scroll kontajner 600px
st.markdown(
    """
<style>
/* Kontajner so scrollom pre tabuľku štatistík */
.sticky-table-container {
  max-height: 600px;     /* požadovaná výška viewportu pre tabuľku */
  overflow: auto;        /* zvyšok scrolluje */
}

/* Stabilné lepenie hlavičky */
.sticky-table-container table {
  border-collapse: separate;  /* dôležité pre position: sticky */
  border-spacing: 0;
}

/* 1. riadok hlavičky (level 0) */
.sticky-table-container thead th.col_heading.level0 {
  position: sticky;
  top: 0;
  z-index: 3;
  background: #fff;
}
/* orientačná výška 1. riadku hlavičky */
.sticky-table-container thead tr:nth-child(1) th.col_heading.level0 {
  height: 36px;
}

/* 2. riadok hlavičky (level 1) */
.sticky-table-container thead th.col_heading.level1 {
  position: sticky;
  top: 36px;   /* zhodné s výškou 1. riadku */
  z-index: 4;
  background: #fff;
}

/* Bold + centrovanie */
.sticky-table-container thead th {
  font-weight: 700 !important;
  text-align: center !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# -- Farby tímov
COLOR_LEFT_BG = "#E6F2FF"  # bledomodrá
COLOR_RIGHT_BG = "#FCE8E8"  # bledočervená


@st.cache_data(show_spinner=False)
def load_data(xlsx_path: str):
    xls = pd.ExcelFile(xlsx_path, engine="openpyxl")
    df_matches = pd.read_excel(xls, sheet_name="Zápasy", engine="openpyxl")
    df_tournaments = pd.read_excel(xls, sheet_name="Turnaje", engine="openpyxl")
    return df_matches, df_tournaments


if not Path(DATA_FILE).exists():
    st.error(f"Nebolo možné nájsť súbor {DATA_FILE} v aktuálnom adresári.")
    st.stop()

# -- DÁTA
df_matches, df_tournaments = load_data(DATA_FILE)

# --- Header (logo + názov + verzia) ---
RAW_LOGO_URL = "https://raw.githubusercontent.com/Jasen77/lefties-righties/main/logo.png"  # placeholder
st.markdown(
    f"""
<div class="header-row">
  <img class="header-logo" src="{RAW_LOGO_URL}" alt="Logo Lefties & Righties" />
  <div class="header-text">
    <h3 class="header-title">{APP_NAME}</h3>
    <div class="header-meta">ver.: {APP_VERSION} ({APP_CREATED})</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# Helpers
# -----------------------------

def _clean_name(x):
    if pd.isna(x):
        return None
    s = str(x).strip()
    return s if s else None


def to_firstname_first(name: str) -> str:
    """Z 'Priezvisko Meno' urobí 'Meno Priezvisko'."""
    if not isinstance(name, str):
        return name
    parts = name.split()
    if len(parts) < 2:
        return name
    first = parts[-1]
    last = " ".join(parts[:-1])
    return f"{first} {last}"


def players_for_year_pairs_only(df_year: pd.DataFrame):
    """Vracia (lefties, righties) zoznamy hráčov pre daný rok – IBA z L1,L2,R1,R2."""
    left_set, right_set = set(), set()
    for _, r in df_year.iterrows():
        for col in ("L1", "L2"):
            nm = _clean_name(r.get(col))
            if nm:
                left_set.add(nm)
        for col in ("R1", "R2"):
            nm = _clean_name(r.get(col))
            if nm:
                right_set.add(nm)
    return (sorted(left_set, key=str.casefold), sorted(right_set, key=str.casefold))


def build_team_table(df_year: pd.DataFrame, players: list[str], side: str) -> pd.DataFrame:
    # Ponechané pre tabuľky v karte Turnaje (nemá vplyv na hlavnú agregáciu v Štatistikách)
    def compute_player_stats(df_year: pd.DataFrame, player: str, side: str):
        if side == 'L':
            mask_pair = ((df_year['L1'] == player) | (df_year['L2'] == player))
            body_pairs = df_year.loc[mask_pair, 'Lbody'].fillna(0).sum() if 'Lbody' in df_year.columns else 0
            matches = int(mask_pair.sum())
        else:
            mask_pair = ((df_year['R1'] == player) | (df_year['R2'] == player))
            body_pairs = df_year.loc[mask_pair, 'Rbody'].fillna(0).sum() if 'Rbody' in df_year.columns else 0
            matches = int(mask_pair.sum())
        body = float(body_pairs)
        return body, matches

    def _format_body(val: float) -> str:
        return f"{int(val)}" if float(val).is_integer() else f"{val:.1f}"

    rows = []
    for p in players:
        body, matches = compute_player_stats(df_year, p, side)
        success = f"{int(round((body / matches) * 100))} %" if matches > 0 else "0 %"
        display_name = to_firstname_first(p)
        rows.append({
            "Por.": None,
            "Hráč": display_name,
            "Body": _format_body(body),
            "Zápasy": matches,
            "Úspešnosť": success,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("Hráč", key=lambda s: s.str.casefold(), inplace=True)
        df.reset_index(drop=True, inplace=True)
        df = df[["Hráč", "Body", "Zápasy", "Úspešnosť"]]
    return df


def style_team_table(df: pd.DataFrame, side: str) -> Styler:
    bg = COLOR_LEFT_BG if side == 'L' else COLOR_RIGHT_BG
    styler = df.style.set_properties(**{"background-color": bg, "width": "auto"})
    cols_to_center = [c for c in df.columns if c != "Hráč"]
    if cols_to_center:
        styler = styler.set_properties(subset=cols_to_center, **{"text-align": "center"})
    styler = styler.set_table_styles([
        {"selector": "th", "props": "font-weight:700; text-align:center;"}
    ])
    try:
        styler = styler.hide(axis="index")
    except Exception:
        styler = styler.hide_index()
    return styler


def style_matches_table(df: pd.DataFrame) -> Styler:
    """Styler pre tabuľku zápasov: riadok podfarbený podľa víťaza, centrovanie, skrytý index, 'Deň' ako celé číslo."""
    if "Deň" in df.columns:
        day_clean = df["Deň"].astype(str).str.strip().str.replace(r"\.$", "", regex=True)
        day_series = pd.to_numeric(day_clean, errors="coerce").astype("Int64")
        df = df.copy()
        df["Deň"] = day_series

    def _row_bg(row: pd.Series):
        w = str(row.get("Víťaz", "")).strip().lower()
        if w == "lefties":
            bg = COLOR_LEFT_BG
        elif w == "righties":
            bg = COLOR_RIGHT_BG
        else:
            bg = "inherit"
        return [f"background-color: {bg}"] * len(row)

    styler = df.style.apply(_row_bg, axis=1)
    if "Deň" in df.columns:
        styler = styler.format(subset=["Deň"], formatter=lambda v: "" if pd.isna(v) else f"{int(v)}")
    cols_to_center = [c for c in df.columns if c in ["Rok", "Deň", "Zápas", "Formát", "Lefties", "Righties", "Víťaz"]]
    if cols_to_center:
        styler = styler.set_properties(subset=cols_to_center, **{"text-align": "center"})
    styler = styler.set_table_styles([
        {"selector": "th", "props": "font-weight:700; text-align:center;"}
    ])
    try:
        styler = styler.hide(axis="index")
    except Exception:
        styler = styler.hide_index()
    return styler


# -----------------------------
# Globálny stav filtra + perzistencia (JSON) – PER-USER
# -----------------------------

# -- Identifikácia používateľa pre per-user JSON

def _current_user_id():
    """Zistí identifikátor používateľa pre názov JSON súboru.
       Pokus: Streamlit experimental_user → fallback: OS login."""
    try:
        u = getattr(st, "experimental_user", None)
        if callable(u):
            info = u()
            if isinstance(info, dict):
                for k in ("username", "email", "name", "user"):
                    if info.get(k):
                        return str(info.get(k))
    except Exception:
        pass
    try:
        import getpass
        return getpass.getuser() or "default"
    except Exception:
        return "default"

_uid = _current_user_id()
_uid_s = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in _uid)
FILTER_JSON_FILE = f"filter_state_{_uid_s}.json"


@dataclass
class FilterState:
    t_all: bool = True
    t_selected: list[str] = field(default_factory=list)            # "Rok - Rezort"
    t_child_map: dict[str, bool] = field(default_factory=dict)     # key -> bool
    teams: list[str] = field(default_factory=lambda: ['Lefties', 'Righties'])
    formats: list[str] = field(default_factory=lambda: ['Foursome', 'Fourball', 'Single'])


FILTER = FilterState()


def _build_tournament_items(df_tournaments: pd.DataFrame) -> list[dict]:
    tdf = df_tournaments.copy()
    if "Rok" in tdf.columns:
        tdf["Rok"] = pd.to_numeric(tdf["Rok"], errors="coerce").astype("Int64")
        tdf = tdf.sort_values("Rok", ascending=False)
    if "Rezort" not in tdf.columns:
        tdf["Rezort"] = ""
    items = []
    for i, r in tdf.iterrows():
        year = r.get("Rok")
        rezort = str(r.get("Rezort", "")).strip()
        key = f"flt_t_{i}"
        label = f"{int(year) if pd.notna(year) else ''} - {rezort}".strip(" -")
        items.append({"key": key, "label": label})
    return items


def update_filter_from_session() -> None:
    FILTER.t_all = st.session_state.get('flt_t_all', False)
    keys = st.session_state.get('flt_t_keys', [])
    FILTER.t_child_map = {k: st.session_state.get(k, False) for k in keys}
    FILTER.t_selected = st.session_state.get('flt_tournaments', [])
    FILTER.teams = st.session_state.get('flt_teams', [])
    FILTER.formats = st.session_state.get('flt_formats', [])


def _save_filter_to_json() -> None:
    data = {
        "version": 1,
        "t_all": st.session_state.get('flt_t_all', True),
        "t_selected_labels": st.session_state.get('flt_tournaments', []),
        "teams": st.session_state.get('flt_teams', []),
        "formats": st.session_state.get('flt_formats', []),
    }
    try:
        Path(FILTER_JSON_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_filter_from_json() -> dict | None:
    p = Path(FILTER_JSON_FILE)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def bootstrap_filter_state() -> None:
    if st.session_state.get('flt_bootstrapped'):
        update_filter_from_session()
        return

    items = _build_tournament_items(df_tournaments)
    st.session_state['flt_t_keys'] = [it['key'] for it in items]

    # Default: všetko zapnuté
    for it in items:
        st.session_state.setdefault(it['key'], True)
    st.session_state.setdefault('flt_t_all', True)
    st.session_state['flt_tournaments'] = [it['label'] for it in items]

    st.session_state.setdefault('flt_team_lefties', True)
    st.session_state.setdefault('flt_team_righties', True)
    st.session_state['flt_teams'] = ['Lefties', 'Righties']

    st.session_state.setdefault('flt_fmt_foursome', True)
    st.session_state.setdefault('flt_fmt_fourball', True)
    st.session_state.setdefault('flt_fmt_single', True)
    st.session_state['flt_formats'] = ['Foursome', 'Fourball', 'Single']

    # Pokus o načítanie z JSON a aplikovanie
    saved = _load_filter_from_json()
    if saved:
        labels_sel = set(saved.get('t_selected_labels', []))
        for it in items:
            st.session_state[it['key']] = it['label'] in labels_sel
        st.session_state['flt_t_all'] = all(st.session_state[k] for k in st.session_state['flt_t_keys'])
        st.session_state['flt_tournaments'] = [it['label'] for it in items if st.session_state[it['key']]]

        teams = saved.get('teams', ['Lefties', 'Righties'])
        st.session_state['flt_team_lefties'] = ('Lefties' in teams)
        st.session_state['flt_team_righties'] = ('Righties' in teams)
        st.session_state['flt_teams'] = teams

        fmts = saved.get('formats', ['Foursome', 'Fourball', 'Single'])
        st.session_state['flt_fmt_foursome'] = ('Foursome' in fmts)
        st.session_state['flt_fmt_fourball'] = ('Fourball' in fmts)
        st.session_state['flt_fmt_single'] = ('Single' in fmts)
        st.session_state['flt_formats'] = fmts

    st.session_state['flt_bootstrapped'] = True
    update_filter_from_session()
    _save_filter_to_json()


def _on_filter_change() -> None:
    items = _build_tournament_items(df_tournaments)

    selected = [it['label'] for it in items if st.session_state.get(it['key'], False)]
    st.session_state['flt_tournaments'] = selected
    st.session_state['flt_t_all'] = all(st.session_state.get(k, False) for k in st.session_state.get('flt_t_keys', []))

    teams = []
    if st.session_state.get('flt_team_lefties'):
        teams.append('Lefties')
    if st.session_state.get('flt_team_righties'):
        teams.append('Righties')
    st.session_state['flt_teams'] = teams

    fmts = []
    if st.session_state.get('flt_fmt_foursome'):
        fmts.append('Foursome')
    if st.session_state.get('flt_fmt_fourball'):
        fmts.append('Fourball')
    if st.session_state.get('flt_fmt_single'):
        fmts.append('Single')
    st.session_state['flt_formats'] = fmts

    update_filter_from_session()
    _save_filter_to_json()


def _toggle_all_tournaments() -> None:
    val = st.session_state.get('flt_t_all', False)
    for k in st.session_state.get('flt_t_keys', []):
        st.session_state[k] = val
    _on_filter_change()


# -- Bootstrap pri štarte
bootstrap_filter_state()


# -----------------------------
# NOVÉ jadro Štatistík podľa pravidiel 1–6
# -----------------------------

def build_player_team_map(df_all: pd.DataFrame) -> dict[str, str]:
    """Zaradenie hráčov do tímov podľa výskytu v L1/L2 (Lefties) a R1/R2 (Righties).
       Pri výskyte v oboch: použijeme vyšší počet; pri rovnosti preferuj Lefties."""
    cntL, cntR = {}, {}
    for col in ("L1", "L2"):
        if col in df_all.columns:
            for nm in df_all[col].dropna().astype(str).str.strip():
                if nm:
                    cntL[nm] = cntL.get(nm, 0) + 1
    for col in ("R1", "R2"):
        if col in df_all.columns:
            for nm in df_all[col].dropna().astype(str).str.strip():
                if nm:
                    cntR[nm] = cntR.get(nm, 0) + 1

    players = set(cntL) | set(cntR)
    team = {}
    for p in players:
        l, r = cntL.get(p, 0), cntR.get(p, 0)
        if l > r:
            team[p] = "Lefties"
        elif r > l:
            team[p] = "Righties"
        else:
            team[p] = "Lefties" if l > 0 else ("Righties" if r > 0 else "Lefties")
    return team


def compute_stats_for_filtered(
    df_matches: pd.DataFrame,
    sel_years: list[int],
    sel_formats: set[str],
    sel_teams: set[str],
    team_map: dict[str, str],
):
    """Prejde vyfiltrované zápasy a spočíta body + zápasy pre hráčov podľa strán.
       LEFT hráči berú Lbody; RIGHT hráči berú Rbody. Formát = stĺpec "Formát"."""
    from collections import defaultdict

    # Guard: ak nie je vybraný žiaden formát, nepočítaj nič
    if sel_formats is not None and len(sel_formats) == 0:
        return [], []

    df_y = df_matches.copy()
    if sel_years:
        df_y = df_y[df_y["Rok"].isin(sel_years)]
    if sel_formats:
        df_y = df_y[df_y["Formát"].isin(sel_formats)]

    FMT_KEYS = ("Foursome", "Fourball", "Single")

    def _empty_bucket():
        return {
            "Team": "",
            "Foursome": {"pts": 0.0, "cnt": 0},
            "Fourball": {"pts": 0.0, "cnt": 0},
            "Single": {"pts": 0.0, "cnt": 0},
        }

    stats = defaultdict(_empty_bucket)

    for _, row in df_y.iterrows():
        fmt = str(row.get("Formát", "")).strip()
        if fmt not in FMT_KEYS:
            continue

        # hráči na ľavej a pravej strane
        left_names, right_names = [], []
        for col in ("L1", "L2"):
            if col in df_y.columns:
                nm = _clean_name(row.get(col))
                if nm:
                    left_names.append(nm)
        for col in ("R1", "R2"):
            if col in df_y.columns:
                nm = _clean_name(row.get(col))
                if nm:
                    right_names.append(nm)

        # body riadku
        lbody = row.get("Lbody", 0)
        rbody = row.get("Rbody", 0)
        try:
            lbody = float(lbody) if lbody is not None else 0.0
        except Exception:
            lbody = 0.0
        try:
            rbody = float(rbody) if rbody is not None else 0.0
        except Exception:
            rbody = 0.0

        # ľavá strana -> Lbody
        for p in left_names:
            p_team = team_map.get(p, "Lefties")
            if sel_teams and (p_team not in sel_teams):
                continue
            b = stats[p]
            b["Team"] = p_team
            b[fmt]["pts"] += lbody
            b[fmt]["cnt"] += 1

        # pravá strana -> Rbody
        for p in right_names:
            p_team = team_map.get(p, "Righties")
            if sel_teams and (p_team not in sel_teams):
                continue
            b = stats[p]
            b["Team"] = p_team
            b[fmt]["pts"] += rbody
            b[fmt]["cnt"] += 1

    def _fmt_points(x: float) -> str:
        return f"{int(x)}" if float(x).is_integer() else f"{x:.1f}"

    def _pct(points_sum: float, cnt: int) -> int:
        return int(round((points_sum / cnt) * 100)) if cnt else 0

    rows_disp, rows_num = [], []
    for p, b in stats.items():
        team = b["Team"] or team_map.get(p, "Lefties")
        fs_pts, fs_cnt = b["Foursome"]["pts"], b["Foursome"]["cnt"]
        fb_pts, fb_cnt = b["Fourball"]["pts"], b["Fourball"]["cnt"]
        si_pts, si_cnt = b["Single"]["pts"], b["Single"]["cnt"]
        total_pts = fs_pts + fb_pts + si_pts
        total_cnt = fs_cnt + fb_cnt + si_cnt

        rows_disp.append({
            'Hráč': to_firstname_first(p),
            'Team': team,
            'Foursome Body': _fmt_points(fs_pts),
            'Foursome Zápasy': fs_cnt,
            'Foursome Úsp.': f"{_pct(fs_pts, fs_cnt)} %",
            'Fourball Body': _fmt_points(fb_pts),
            'Fourball Zápasy': fb_cnt,
            'Fourball Úsp.': f"{_pct(fb_pts, fb_cnt)} %",
            'Single Body': _fmt_points(si_pts),
            'Single Zápasy': si_cnt,
            'Single Úsp.': f"{_pct(si_pts, si_cnt)} %",
            'Spolu Body': _fmt_points(total_pts),
            'Spolu Zápasy': total_cnt,
            'Spolu Úsp.': f"{_pct(total_pts, total_cnt)} %",
        })

        rows_num.append({
            'Hráč': to_firstname_first(p),
            'Team': team,
            'Foursome Body': float(fs_pts),
            'Foursome Zápasy': int(fs_cnt),
            'Foursome Úsp.': _pct(fs_pts, fs_cnt),
            'Fourball Body': float(fb_pts),
            'Fourball Zápasy': int(fb_cnt),
            'Fourball Úsp.': _pct(fb_pts, fb_cnt),
            'Single Body': float(si_pts),
            'Single Zápasy': int(si_cnt),
            'Single Úsp.': _pct(si_pts, si_cnt),
            'Spolu Body': float(total_pts),
            'Spolu Zápasy': int(total_cnt),
            'Spolu Úsp.': _pct(total_pts, total_cnt),
        })

    return rows_disp, rows_num


# -----------------------------
# UI – Tabs: Turnaje | Štatistiky | Filter
# -----------------------------

tab_turnaje, tab_stats, tab_filter = st.tabs(["Turnaje", "Štatistiky", "Filter"])


# -----------------------------
# Štatistiky
# -----------------------------
with tab_stats:
    st.subheader("Štatistiky")

    # -- Súhrn aktuálneho filtra (len riadky; prvý riadok začína **Turnaje:**)
    def _filter_summary_from_global() -> str:
        if FILTER.t_all:
            t_str = "všetky turnaje"
        else:
            years = []
            for lbl in FILTER.t_selected:
                try:
                    y = int(str(lbl).split(' - ')[0].strip())
                    years.append(str(y))
                except Exception:
                    pass
            t_str = ", ".join(sorted(set(years))) if years else "—"
        teams_str = ", ".join(FILTER.teams) if FILTER.teams else "—"
        fmts_str = ", ".join(FILTER.formats) if FILTER.formats else "—"
        return (
            f"**Turnaje:** {t_str}  \n"
            f"**Tímy:** {teams_str}  \n"
            f"**Formáty:** {fmts_str}"
        )
    st.markdown(_filter_summary_from_global())

    # --- Roky z FILTER.t_selected ---
    years_list = []
    for lbl in FILTER.t_selected:
        try:
            years_list.append(int(str(lbl).split(' - ')[0].strip()))
        except Exception:
            pass
    years_list = sorted(set(years_list))

    # --- Filtre ---
    sel_years   = years_list
    sel_formats = set(FILTER.formats)
    sel_teams   = set(FILTER.teams)

    # --- Team mapa a prepočet ---
    player_team_map = build_player_team_map(df_matches)
    rows_disp, rows_num = compute_stats_for_filtered(
        df_matches=df_matches,
        sel_years=sel_years,
        sel_formats=sel_formats,
        sel_teams=sel_teams,
        team_map=player_team_map,
    )

    import pandas as pd
    df_disp = pd.DataFrame(rows_disp)
    df_num  = pd.DataFrame(rows_num)

    if df_disp.empty:
        st.info("Pre zvolený filter nie sú k dispozícii dáta na zobrazenie.")
    else:
        # --- DYNAMICKÉ tlačidlá triedenia + výber stĺpcov podľa sel_formats ---
        import locale

        def _set_sk_locale_once():
            if 'sk_locale_ok' in st.session_state:
                return
            ok = False
            for loc in ('sk_SK.UTF-8', 'sk_SK', 'Slovak_Slovakia.1250', 'cs_CZ.UTF-8', 'cs_CZ'):
                try:
                    locale.setlocale(locale.LC_COLLATE, loc)
                    ok = True
                    break
                except Exception:
                    pass
            st.session_state['sk_locale_ok'] = ok

        def _sk_xfrm(s: str) -> str:
            return locale.strxfrm(s) if st.session_state.get('sk_locale_ok') else s.casefold()

        def _surname(full_name: str) -> str:
            if not isinstance(full_name, str):
                return ''
            parts = full_name.strip().split()
            return parts[-1] if parts else ''

        _set_sk_locale_once()

        FORMAT_ORDER = [('Foursome', 'Fs'), ('Fourball', 'Fb'), ('Single', 'Si')]
        included = [(fmt, tag) for fmt, tag in FORMAT_ORDER if fmt in sel_formats]

        _sort_map = {}
        for fmt, tag in included:
            _sort_map[f'{tag}B'] = f'{fmt} Body'
            _sort_map[f'{tag}Z'] = f'{fmt} Zápasy'
            _sort_map[f'{tag}Ú'] = f'{fmt} Úsp.'

        row_items = ['Abc']
        for _, tag in included:
            row_items += ['sep', f'{tag}B', f'{tag}Z', f'{tag}Ú']
        if included:
            row_items += ['sep']
        row_items += ['SpB', 'SpZ', 'SpÚ']

        spec = [(0.35 if it == 'sep' else 1.0) for it in row_items]

        active_token = None
        if 'stats_sort' in st.session_state:
            sort_key, _ = st.session_state['stats_sort']
            if sort_key == 'ABC':
                active_token = 'Abc'
            elif sort_key in ('Spolu Body', 'Spolu Zápasy', 'Spolu Úsp.'):
                active_token = {'Spolu Body': 'SpB', 'Spolu Zápasy': 'SpZ', 'Spolu Úsp.': 'SpÚ'}[sort_key]
            else:
                for token, colname in _sort_map.items():
                    if colname == sort_key:
                        active_token = token
                        break

        cols = st.columns(spec)
        for i, it in enumerate(row_items):
            if it == 'sep':
                cols[i].markdown(" ", unsafe_allow_html=True)
                continue

            # marker pred tlačidlom (pre zvýraznenie aktívneho)
            if it == active_token:
                cols[i].markdown('<span class="marker sort-active"></span>', unsafe_allow_html=True)
            else:
                cols[i].markdown('<span class="marker"></span>', unsafe_allow_html=True)

            # Prefix v labeli pre istotu (viditeľné aj bez CSS)
            # prefix = "• "
            # label = f"{prefix}{it}" if it == active_token else it
            label = it

            if cols[i].button(it, use_container_width=True, key=f"stats_sort_btn_{it}"):
                if it == 'Abc':
                    st.session_state['stats_sort'] = ('ABC', True)
                elif it in ('SpB', 'SpZ', 'SpÚ'):
                    name = {'SpB': 'Spolu Body', 'SpZ': 'Spolu Zápasy', 'SpÚ': 'Spolu Úsp.'}[it]                    
                    st.session_state['stats_sort'] = (name, False)
                else:
                    st.session_state['stats_sort'] = (_sort_map[it], False)

        allowed_sort_cols = {'ABC', 'Spolu Body', 'Spolu Zápasy', 'Spolu Úsp.'}
        allowed_sort_cols |= set(_sort_map.values())
        if ('stats_sort' not in st.session_state) or (st.session_state['stats_sort'][0] not in allowed_sort_cols):
            st.session_state['stats_sort'] = ('Spolu Body', False)

        sort_key, sort_asc = st.session_state['stats_sort']
        if sort_key == 'ABC':
            df_disp['_sort1'] = df_disp['Hráč'].apply(lambda x: _sk_xfrm(_surname(x)))
            df_disp['_sort2'] = df_disp['Hráč'].apply(lambda x: _sk_xfrm(x))
            df_disp.sort_values(by=['_sort1','_sort2'], ascending=[True, True], inplace=True)
            df_disp.drop(columns=['_sort1','_sort2'], inplace=True)
        else:
            df_disp['_sort_val'] = df_num[sort_key]
            df_disp['_sort_name'] = df_disp['Hráč'].apply(lambda x: _sk_xfrm(x))
            df_disp.sort_values(by=['_sort_val','_sort_name'], ascending=[sort_asc, True], inplace=True)
            df_disp.drop(columns=['_sort_val','_sort_name'], inplace=True)

        flat_order = ['Por.', 'Hráč', 'Team']
        for fmt, _ in included:
            flat_order += [f'{fmt} Body', f'{fmt} Zápasy', f'{fmt} Úsp.']
        flat_order += ['Spolu Body', 'Spolu Zápasy', 'Spolu Úsp.']

        if 'Por.' in df_disp.columns:
            df_disp['Por.'] = range(1, len(df_disp) + 1)
        else:
            df_disp.insert(0, 'Por.', range(1, len(df_disp) + 1))
        df_disp = df_disp[flat_order]

        col_tuples = [('', 'Por.'), ('', 'Hráč'), ('', 'Team')]
        for fmt, _ in included:
            col_tuples += [(fmt, 'Body'), (fmt, 'Zápasy'), (fmt, 'Úsp.')]
        col_tuples += [('Spolu', 'Body'), ('Spolu', 'Zápasy'), ('Spolu', 'Úsp.')]
        df_disp.columns = pd.MultiIndex.from_tuples(col_tuples)

        def _col_tuple_for_sort_key(sk: str):
            if sk == 'ABC':
                return ('', 'Hráč')
            if sk in ('Spolu Body', 'Spolu Zápasy', 'Spolu Úsp.'):
                return ('Spolu', sk.split()[-1])
            try:
                fmt, metric = sk.split(' ', 1)
                return (fmt, metric)
            except Exception:
                return None

        col_to_bold = _col_tuple_for_sort_key(sort_key)

        def style_stats_table(df: pd.DataFrame, highlight_col=None) -> Styler:
            styler = df.style.set_table_styles([
                {"selector": "th.col_heading", "props": "font-weight:700; text-align:center;"},
                {"selector": "th.col_heading.level0", "props": "font-weight:700; text-align:center;"},
                {"selector": "th.col_heading.level1", "props": "font-weight:700; text-align:center;"},
            ])
            cols_center = [c for c in df.columns if c != ('', 'Hráč')]
            if cols_center:
                styler = styler.set_properties(subset=cols_center, **{"text-align": "center"})

            def _row_bg(row):
                team = str(row.get(('', 'Team'), '')).strip()
                if team == 'Lefties':
                    bg = COLOR_LEFT_BG
                elif team == 'Righties':
                    bg = COLOR_RIGHT_BG
                else:
                    bg = 'inherit'
                return [f'background-color: {bg}'] * len(row)

            styler = styler.apply(_row_bg, axis=1)

            if highlight_col and highlight_col in df.columns:
                styler = styler.set_properties(
                    subset=(slice(None), [highlight_col]),
                    **{"font-weight": "700", "font-size": "1.05rem"}
                )

            try:
                styler = styler.hide(axis='index')
            except Exception:
                styler = styler.hide_index()
            return styler

        sty = style_stats_table(df_disp, highlight_col=col_to_bold)
        html = sty.to_html()
        html_wrapped = f'<div class="sticky-table-container">{html}</div>'
        st.markdown(html_wrapped, unsafe_allow_html=True)


# -----------------------------
# Filter
# -----------------------------
with tab_filter:
    st.subheader("Filter")
    c1, c2 = st.columns([2, 1])

    with c1:
        st.markdown("### Turnaje")
        tournament_items = _build_tournament_items(df_tournaments)
        st.session_state.setdefault('flt_t_keys', [it['key'] for it in tournament_items])

        # Master
        st.checkbox("Všetky turnaje", key='flt_t_all', on_change=_toggle_all_tournaments)

        # Deti
        for item in tournament_items:
            st.session_state.setdefault(item['key'], True)
            st.checkbox(item['label'], key=item['key'], on_change=_on_filter_change)

        selected_tournaments = [it['label'] for it in tournament_items if st.session_state.get(it['key'], False)]
        st.session_state['flt_tournaments'] = selected_tournaments
        st.caption(f"Vybrané turnaje: {len(selected_tournaments)}/{len(tournament_items)}")

    with c2:
        st.markdown("### Tímy")
        st.checkbox("Lefties", key='flt_team_lefties', on_change=_on_filter_change)
        st.checkbox("Righties", key='flt_team_righties', on_change=_on_filter_change)

        st.markdown("### Formáty hry")
        st.checkbox("Foursome", key='flt_fmt_foursome', on_change=_on_filter_change)
        st.checkbox("Fourball", key='flt_fmt_fourball', on_change=_on_filter_change)
        st.checkbox("Single", key='flt_fmt_single', on_change=_on_filter_change)


# -----------------------------
# Turnaje
# -----------------------------
with tab_turnaje:
    st.subheader("Turnaje")
    tdf = df_tournaments.copy()
    if "Rok" in tdf.columns:
        tdf.sort_values("Rok", ascending=False, inplace=True)

    if 'open_year' not in st.session_state:
        st.session_state['open_year'] = None

    for _, t in tdf.iterrows():
        year = int(t.get('Rok')) if pd.notna(t.get('Rok')) else None
        rezort = str(t.get('Rezort', '')).strip()
        l_captain = str(t.get('L-Captain', '')).strip()
        r_captain = str(t.get('R-Captain', '')).strip()
        winner_val = str(t.get('Víťaz', '')).strip().lower()
        btn_icon = '🔵' if winner_val == 'lefties' else ('🔴' if winner_val == 'righties' else '⚪')
        btn_label = f"{btn_icon}    {year}     {rezort}"
        clicked = st.button(btn_label, key=f"btn_{year}")
        if clicked:
            st.session_state['open_year'] = year if st.session_state.get('open_year') != year else None
        if st.session_state.get('open_year') == year:
            logo_url = str(t.get('Logo', '')).strip()
            if logo_url:
                st.image(logo_url, width=240)

            df_y = df_matches[df_matches['Rok'] == year].copy()
            l_total = float(df_y['Lbody'].fillna(0).sum()) if 'Lbody' in df_y.columns else 0.0
            r_total = float(df_y['Rbody'].fillna(0).sum()) if 'Rbody' in df_y.columns else 0.0

            def _fmt(v: float) -> str:
                return f"{int(v)}" if float(v).is_integer() else f"{v:.1f}"

            st.markdown(f"**Výsledok turnaja {year}:** Lefties **{_fmt(l_total)}** : **{_fmt(r_total)}** Righties")

            val_L = t.get('StavL', t.get('Stav L', None))
            val_R = t.get('StavR', t.get('Stav R', None))
            try:
                val_L = float(val_L) if val_L is not None else 0.0
            except Exception:
                val_L = 0.0
            try:
                val_R = float(val_R) if val_R is not None else 0.0
            except Exception:
                val_R = 0.0
            st.markdown(f"**Stav na konci turnaja {year}:** Lefties **{_fmt(val_L)}** : **{_fmt(val_R)}** Righties")

            df_y = df_matches[df_matches['Rok'] == year].copy()
            left_players, right_players = players_for_year_pairs_only(df_y)
            left_table = build_team_table(df_y, left_players, side='L')
            right_table = build_team_table(df_y, right_players, side='R')
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"### Team Lefties {year}  \n(kapitán: {to_firstname_first(l_captain)})")
                if not left_table.empty:
                    sty = style_team_table(left_table, 'L')
                    st.markdown(f"{sty.to_html()}", unsafe_allow_html=True)
                else:
                    st.info("Pre tento rok nie sú v dátach hráči tímu Lefties.")
            with c2:
                st.markdown(f"### Team Righties {year}  \n(kapitán: {to_firstname_first(r_captain)})")
                if not right_table.empty:
                    sty = style_team_table(right_table, 'R')
                    st.markdown(f"{sty.to_html()}", unsafe_allow_html=True)
                else:
                    st.info("Pre tento rok nie sú v dátach hráči tímu Righties.")

            st.markdown("---")
            wanted_cols = ["Rok", "Deň", "Zápas", "Formát", "Lefties", "Righties", "Víťaz"]
            cols_present = [c for c in wanted_cols if c in df_y.columns]
            matches_view = df_y[cols_present].copy()
            st.markdown(f"### Zápasy {year}")
            sty = style_matches_table(matches_view)
            st.markdown(f"{sty.to_html()}", unsafe_allow_html=True)

            photo_url = str(t.get('Photo', '')).strip()
            if photo_url:
                st.image(photo_url,  width=800)
            #     st.image(photo_url,  use_container_width=True)
            st.markdown("")
