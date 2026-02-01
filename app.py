# app.py — Lefties & Righties (mobile-friendly)
# ------------------------------------------------------------
# V tomto refactore:
# - Sidebar nahradený expanderom "Filtre" v hlavičke.
# - Pridaný prepínač "Mobilné zobrazenie" (kompaktnejšie tabuľky).
# - Tabs: Prehľad | Hráč | Export.
# - Logo "logo.png" v koreňovom adresári (favicon + hlavička).
# - Zachované výpočty a export do Excelu (formátovanie).
# ------------------------------------------------------------

import os
import re
from collections import defaultdict
from io import BytesIO
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

# Cesta k Excelu s dátami
EXCEL_PATH = "GolfData.xlsx"

# ------------------------------------------------------------
# Slovenské triedenie mien (vrátane digrafu "ch")
# ------------------------------------------------------------
_SK_ORDER = [
    "a", "á", "ä", "b", "c", "č", "d", "ď", "e", "é", "f", "g", "h", "ch",
    "i", "í", "j", "k", "l", "ĺ", "ľ", "m", "n", "ň", "o", "ó", "ô", "p",
    "q", "r", "ŕ", "s", "š", "t", "ť", "u", "ú", "v", "w", "x", "y", "ý", "z", "ž"
]
_SK_INDEX = {ch: i for i, ch in enumerate(_SK_ORDER)}
_CH_RE = re.compile(r"ch", flags=re.IGNORECASE)
_PLACEHOLDER = "¤"


def _tokenize_sk(s: str) -> List[str]:
    s = (s or "").strip().lower()
    if not s:
        return []
    s = _CH_RE.sub(_PLACEHOLDER, s)
    tokens = ["ch" if ch == _PLACEHOLDER else ch for ch in s]
    return [t for t in tokens if t in _SK_INDEX]


def sk_sort_key(name: str):
    if not isinstance(name, str):
        name = "" if pd.isna(name) else str(name)
    tokens = _tokenize_sk(name)
    if not tokens:
        return (len(_SK_ORDER) + 1,)
    return tuple(_SK_INDEX[t] for t in tokens)


# ------------------------------------------------------------
# Načítanie dát
# ------------------------------------------------------------
@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    for col in ["Rok", "Deň", "Zápas", "Lbody", "Rbody"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip()
    if {"Rok", "Deň", "Zápas"}.issubset(df.columns):
        df = df.sort_values(["Rok", "Deň", "Zápas"], ascending=[True, True, True])
    return df


@st.cache_data
def load_tournaments(path: str) -> pd.DataFrame:
    # 2. list: "Turnaje" (alebo index 1)
    try:
        t = pd.read_excel(path, sheet_name="Turnaje", engine="openpyxl")
    except Exception:
        t = pd.read_excel(path, sheet_name=1, engine="openpyxl")
    t.columns = [str(c).strip() for c in t.columns]
    col_year = "Turnaje" if "Turnaje" in t.columns else t.columns[0]
    col_resort = "Ihrisko" if "Ihrisko" in t.columns else t.columns[1]
    out = t[[col_year, col_resort]].rename(columns={col_year: "Rok", col_resort: "Rezort"})
    out["Rok"] = pd.to_numeric(out["Rok"], errors="coerce").astype("Int64")
    out = out.dropna(subset=["Rok"]).astype({"Rok": int}).sort_values("Rok").reset_index(drop=True)
    return out


# ------------------------------------------------------------
# Výpočty bodov a štatistík
# ------------------------------------------------------------
def _norm_name(x) -> str:
    s = "" if pd.isna(x) else str(x).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return ""
    return s


def _series_from_cols(df: pd.DataFrame, cols: List[str]) -> pd.Series:
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return pd.Series(dtype="object")
    s = pd.concat([df[c] for c in cols], ignore_index=True).map(_norm_name)
    return s[s != ""]


def _compute_player_points(d: pd.DataFrame) -> Dict[str, float]:
    pts = defaultdict(float)
    has_L1, has_L2 = "L1" in d.columns, "L2" in d.columns
    has_R1, has_R2 = "R1" in d.columns, "R2" in d.columns
    has_Lb, has_Rb = "Lbody" in d.columns, "Rbody" in d.columns
    for row in d.itertuples(index=False):
        Lb = float(getattr(row, "Lbody", 0) if has_Lb else 0) or 0.0
        Rb = float(getattr(row, "Rbody", 0) if has_Rb else 0) or 0.0
        if has_L1:
            n = _norm_name(getattr(row, "L1"))
            if n:
                pts[n] += Lb
        if has_L2:
            n = _norm_name(getattr(row, "L2"))
            if n:
                pts[n] += Lb
        if has_R1:
            n = _norm_name(getattr(row, "R1"))
            if n:
                pts[n] += Rb
        if has_R2:
            n = _norm_name(getattr(row, "R2"))
            if n:
                pts[n] += Rb
    return dict(pts)


def _counts_by_format(d: pd.DataFrame) -> Dict[str, pd.Series]:
    out = {}
    for fmt in ["Foursome", "Fourball", "Single"]:
        sub = d[d["Formát"] == fmt] if "Formát" in d.columns else d.iloc[0:0]
        left = _series_from_cols(sub, ["L1", "L2"])
        right = _series_from_cols(sub, ["R1", "R2"])
        out[fmt] = left.value_counts().add(right.value_counts(), fill_value=0).astype(int)
    return out


def _points_by_format(d: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    out = {}
    for fmt in ["Foursome", "Fourball", "Single"]:
        sub = d[d["Formát"] == fmt] if "Formát" in d.columns else d.iloc[0:0]
        out[fmt] = _compute_player_points(sub)
    return out


def _success_str(body: float, zapasy: int) -> str:
    if zapasy <= 0:
        return "0%"
    return f"{int(round((body / zapasy) * 100, 0))}%"


def _success_num(body: float, zapasy: int) -> float:
    return 0.0 if zapasy <= 0 else (body / zapasy) * 100.0


def _fmt_points(x: float) -> str:
    if pd.isna(x):
        return ""
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x))}"
    # ak .5, zobraz 1 desatinné
    if abs((x * 2) - round(x * 2)) < 1e-9 and int(round(x * 2)) % 2 == 1:
        return f"{x:.1f}"
    return f"{int(round(x))}"


@st.cache_data
def players_summary(df: pd.DataFrame, years: List[int] = None, formats: List[str] = None) -> pd.DataFrame:
    d = df
    if years is not None and len(years) == 0:
        return pd.DataFrame()
    if years:
        d = d[d["Rok"].isin(years)]
    if formats and "Formát" in d.columns:
        d = d[d["Formát"].isin(formats)]

    left_all = set(_series_from_cols(d, ["L1", "L2"]).unique().tolist())
    right_all = set(_series_from_cols(d, ["R1", "R2"]).unique().tolist())

    cnt_fmt = _counts_by_format(d)
    pts_fmt = _points_by_format(d)

    all_players = set()
    for s in cnt_fmt.values():
        all_players |= set(s.index.tolist())
    for m in pts_fmt.values():
        all_players |= set(m.keys())
    all_players = sorted(all_players, key=sk_sort_key)

    rows = []
    for p in all_players:
        f_cnt = {fmt: int(cnt_fmt.get(fmt, pd.Series(dtype=int)).get(p, 0)) for fmt in ["Foursome", "Fourball", "Single"]}
        f_pts = {fmt: float(pts_fmt.get(fmt, {}).get(p, 0.0)) for fmt in ["Foursome", "Fourball", "Single"]}
        team = ("Oboje" if (p in left_all and p in right_all) else ("Lefties" if p in left_all else "Righties"))
        total_cnt = sum(f_cnt.values())
        total_pts = round(sum(f_pts.values()), 1)
        rows.append({
            "Hráč": p,
            "Team": team,
            # Foursome
            "Foursome Body": round(f_pts["Foursome"], 1),
            "Foursome Zápasy": f_cnt["Foursome"],
            "Foursome Úspešnosť": _success_str(f_pts["Foursome"], f_cnt["Foursome"]),
            "_Foursome_Usp_num": _success_num(f_pts["Foursome"], f_cnt["Foursome"]),
            # Fourball
            "Fourball Body": round(f_pts["Fourball"], 1),
            "Fourball Zápasy": f_cnt["Fourball"],
            "Fourball Úspešnosť": _success_str(f_pts["Fourball"], f_cnt["Fourball"]),
            "_Fourball_Usp_num": _success_num(f_pts["Fourball"], f_cnt["Fourball"]),
            # Single
            "Single Body": round(f_pts["Single"], 1),
            "Single Zápasy": f_cnt["Single"],
            "Single Úspešnosť": _success_str(f_pts["Single"], f_cnt["Single"]),
            "_Single_Usp_num": _success_num(f_pts["Single"], f_cnt["Single"]),
            # Spolu
            "Spolu Body": total_pts,
            "Spolu Zápasy": int(total_cnt),
            "Spolu Úspešnosť": _success_str(total_pts, total_cnt),
            "_Spolu_Usp_num": _success_num(total_pts, total_cnt),
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(
            by=["Team", "Hráč"],
            key=lambda col: (col.map({"Lefties": 0, "Righties": 1, "Oboje": 2}) if col.name == "Team" else col.map(sk_sort_key)),
        ).reset_index(drop=True)
    return out


# ------------------------------------------------------------
# Pomocné pre hráča (detail + súhrny)
# ------------------------------------------------------------
def _summaries_for_player(d: pd.DataFrame, player: str, rok_to_rezort: Dict[int, str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    def _accumulate(dd: pd.DataFrame) -> dict:
        matches, pts = 0, 0.0
        for row in dd.itertuples(index=False):
            L1 = _norm_name(getattr(row, "L1", "")) if "L1" in dd.columns else ""
            L2 = _norm_name(getattr(row, "L2", "")) if "L2" in dd.columns else ""
            R1 = _norm_name(getattr(row, "R1", "")) if "R1" in dd.columns else ""
            R2 = _norm_name(getattr(row, "R2", "")) if "R2" in dd.columns else ""
            Lb = float(getattr(row, "Lbody", 0) if "Lbody" in dd.columns else 0) or 0.0
            Rb = float(getattr(row, "Rbody", 0) if "Rbody" in dd.columns else 0) or 0.0
            on_left = (player.casefold() in L1.casefold()) or (player and player.casefold() in L2.casefold())
            on_right = (player.casefold() in R1.casefold()) or (player and player.casefold() in R2.casefold())
            if on_left or on_right:
                matches += 1
                if on_left: pts += Lb
                if on_right: pts += Rb
        return {"Zápasy_num": int(matches), "Body_num": float(pts)}

    # podľa formátu
    fmt_rows = []
    for fmt in ["Foursome", "Fourball", "Single"]:
        sub = d[d["Formát"] == fmt] if "Formát" in d.columns else d.iloc[0:0]
        agg = _accumulate(sub)
        fmt_rows.append({"Formát": fmt, **agg})
    df_fmt_num = pd.DataFrame(fmt_rows)

    # podľa roku (s rezortom)
    yr_rows = []
    if "Rok" in d.columns:
        for rok, sub in d.groupby("Rok", sort=True):
            agg = _accumulate(sub)
            rez = rok_to_rezort.get(int(rok), "")
            yr_rows.append({"Rok": int(rok), "Rezort": rez, **agg})
    df_year_num = (pd.DataFrame(yr_rows).sort_values("Rok")
                   if yr_rows else pd.DataFrame(columns=["Rok", "Rezort", "Body_num", "Zápasy_num"]))

    # display verzie
    def _make_display(df_num: pd.DataFrame, label_col: str) -> pd.DataFrame:
        if df_num.empty:
            cols = [label_col, "Body", "Zápasy", "Úspešnosť"]
            if label_col == "Rok":
                cols.insert(1, "Rezort")
            return pd.DataFrame(columns=cols)
        total_body = float(df_num["Body_num"].sum())
        total_zap = int(df_num["Zápasy_num"].sum())
        if label_col == "Rok":
            disp = pd.DataFrame({
                "Rok": df_num["Rok"].astype(int),
                "Rezort": df_num.get("Rezort", ""),
                "Body": df_num["Body_num"].map(_fmt_points),
                "Zápasy": df_num["Zápasy_num"].astype(int),
                "Úspešnosť": [_success_str(b, z) for b, z in zip(df_num["Body_num"], df_num["Zápasy_num"])],
            })
            sum_row = {"Rok": "Spolu", "Rezort": "", "Body": _fmt_points(total_body), "Zápasy": total_zap,
                       "Úspešnosť": _success_str(total_body, total_zap)}
            disp = pd.concat([disp, pd.DataFrame([sum_row])], ignore_index=True)
            return disp
        # label_col == "Formát"
        disp = pd.DataFrame({
            "Formát": df_num["Formát"],
            "Body": df_num["Body_num"].map(_fmt_points),
            "Zápasy": df_num["Zápasy_num"].astype(int),
            "Úspešnosť": [_success_str(b, z) for b, z in zip(df_num["Body_num"], df_num["Zápasy_num"])],
        })
        sum_row = {"Formát": "Spolu", "Body": _fmt_points(total_body), "Zápasy": total_zap,
                   "Úspešnosť": _success_str(total_body, total_zap)}
        disp = pd.concat([disp, pd.DataFrame([sum_row])], ignore_index=True)
        return disp

    return _make_display(df_fmt_num, "Formát"), _make_display(df_year_num, "Rok")


# ------------------------------------------------------------
# Excel formátovanie (export)
# ------------------------------------------------------------
def _excel_center_and_bold(ws):
    center = Alignment(horizontal="center", vertical="center", wrap_text=False)
    bold = Font(bold=True)
    # hlavička
    for cell in ws[1]:
        cell.alignment = center
        cell.font = bold
    # telo
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = center


def _excel_set_col_widths(ws, widths: Dict[str, float]):
    header_map = {cell.value: idx + 1 for idx, cell in enumerate(ws[1])}
    for name, width in widths.items():
        if name in header_map:
            col_letter = get_column_letter(header_map[name])
            ws.column_dimensions[col_letter].width = float(width)


def _excel_set_percent_format(ws, percent_headers: List[str]):
    header_map = {cell.value: idx + 1 for idx, cell in enumerate(ws[1])}
    for name in percent_headers:
        if name in header_map:
            col_idx = header_map[name]
            for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
                for cell in row:
                    cell.number_format = "0%"


# ------------------------------------------------------------
# UI — main()
# ------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Lefties & Righties",
        page_icon="logo.png",        # logo v koreňovom adresári
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # LOGO + titul + prepínač mobilného režimu
    c_logo, c_title, c_toggle = st.columns([1, 4, 2], gap="small")
    with c_logo:
        if os.path.exists("logo.png"):
            st.image("logo.png", use_column_width=True)
    with c_title:
        st.markdown(
            """
            <div style="display:flex; align-items:flex-end; gap:.5rem; height:100%;">
              <h1 style="margin:0 0 .2rem 0;">Lefties & Righties</h1>
              <div style="color:#666; font-style:italic;">...more than golf</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c_toggle:
        mobile_mode = st.toggle("Mobilné zobrazenie", value=True,
                                help="Kompaktnejšie tabuľky a rozloženie pre telefón")

    # Globálny CSS (sticky header, kompaktné DF, centrovanie)
    st.markdown("""
    <style>
    /* Sticky horný header (prvý blok po page_config) */
    div.block-container > div:first-child {
      position: sticky; top: 0; z-index: 99;
      background: var(--background-color);
      padding-top: .25rem; padding-bottom: .25rem;
    }
    /* Kompaktnejšie ovládacie prvky a bunky na mobiloch */
    @media (max-width: 640px) {
      .stButton>button, .stDownloadButton>button { padding: .4rem .6rem; }
      .stSelectbox, .stMultiSelect, .stTextInput, .stNumberInput, .stRadio, .stCheckbox { font-size: 0.95rem; }
      [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th { padding: .25rem .4rem !important; }
    }
    /* DataFrame – centrovanie + sticky hlavička */
    [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th { text-align: center !important; }
    [data-testid="stDataFrame"] td p, [data-testid="stDataFrame"] th p { text-align: center !important; margin: 0; }
    [data-testid="stDataFrame"] thead tr th { position: sticky; top: 0; z-index: 2; background: var(--background-color); }
    </style>
    """, unsafe_allow_html=True)

    # Dáta
    df = load_data(EXCEL_PATH)
    tourn = load_tournaments(EXCEL_PATH)
    tourn_map = dict(zip(tourn["Rok"], tourn["Rezort"]))

    # Filtre (expander)
    with st.expander("Filtre", expanded=False):
        st.subheader("Turnaje")
        years_asc = tourn["Rok"].tolist()
        resorts_asc = tourn["Rezort"].tolist()
        max_year = max(years_asc) if years_asc else None

        years_desc = years_asc[::-1]
        resorts_desc = resorts_asc[::-1]

        all_selected = st.checkbox("Všetky turnaje", value=False, help="Zaškrtne/odškrtne všetky roky")

        selected_years_list: List[int] = []
        cols = st.columns(2 if mobile_mode else 4)
        for i, (yr, rez) in enumerate(zip(years_desc, resorts_desc)):
            with cols[i % len(cols)]:
                key = f"chk_year_{yr}"
                # default: označ posledný rok, inak podľa all_selected
                default_val = True if all_selected else (yr == max_year if key not in st.session_state else st.session_state[key])
                val = st.checkbox(f"{yr} – {rez}", key=key, value=default_val)
                if val:
                    selected_years_list.append(int(yr))

        st.subheader("Formát")
        fmt_options = ["Foursome", "Fourball", "Single"]
        c1, c2, c3 = st.columns(3)
        fmt_selected = []
        with c1:
            if st.checkbox("Foursome", value=True, key="fmt_foursome"): fmt_selected.append("Foursome")
        with c2:
            if st.checkbox("Fourball", value=True, key="fmt_fourball"): fmt_selected.append("Fourball")
        with c3:
            if st.checkbox("Single", value=True, key="fmt_single"): fmt_selected.append("Single")

        st.subheader("Team")
        cL, cR = st.columns(2)
        team_left = cL.checkbox("Lefties", value=True, key="team_left")
        team_right = cR.checkbox("Righties", value=True, key="team_right")
        selected_team_set = set()
        if team_left: selected_team_set.add("Lefties")
        if team_right: selected_team_set.add("Righties")

        st.subheader("Zoradenie")
        sort_col = st.radio(
            label="",
            options=[
                "Priezviska hráča",
                "Spolu – Body",
                "Spolu – Zápasy",
                "Spolu – Úspešnosť",
                "Foursome – Úspešnosť",
                "Fourball – Úspešnosť",
                "Single – Úspešnosť",
            ],
            index=0,
            horizontal=True if mobile_mode else False,
            key="sort_radio"
        )

    # Zhrnutie hráčov podľa filtrov
    if selected_years_list:
        players_all = players_summary(df, selected_years_list, fmt_selected)
    else:
        players_all = pd.DataFrame()

    if players_all.empty:
        players_view = players_all.copy()
    else:
        if team_left and team_right:
            players_view = players_all.copy()
        elif team_left and not team_right:
            players_view = players_all[players_all["Team"] == "Lefties"].copy()
        elif team_right and not team_left:
            players_view = players_all[players_all["Team"] == "Righties"].copy()
        else:
            players_view = players_all.iloc[0:0].copy()

    # Triedenie
    if not players_view.empty:
        if sort_col == "Priezviska hráča":
            players_view = players_view.sort_values(by="Hráč", key=lambda s: s.map(sk_sort_key), ascending=True)
        elif sort_col == "Spolu – Body":
            players_view = players_view.sort_values(by=["Spolu Body", "_Spolu_Usp_num"], ascending=[False, False])
        elif sort_col == "Spolu – Zápasy":
            players_view = players_view.sort_values(by=["Spolu Zápasy", "_Spolu_Usp_num"], ascending=[False, False])
        elif sort_col == "Spolu – Úspešnosť":
            players_view = players_view.sort_values(by=["_Spolu_Usp_num", "Spolu Zápasy"], ascending=[False, False])
        elif sort_col == "Foursome – Úspešnosť":
            players_view = players_view.sort_values(by=["_Foursome_Usp_num", "Foursome Zápasy"], ascending=[False, False])
        elif sort_col == "Fourball – Úspešnosť":
            players_view = players_view.sort_values(by=["_Fourball_Usp_num", "Fourball Zápasy"], ascending=[False, False])
        elif sort_col == "Single – Úspešnosť":
            players_view = players_view.sort_values(by=["_Single_Usp_num", "Single Zápasy"], ascending=[False, False])

        players_view = players_view.reset_index(drop=True)
        if "Poradie" not in players_view.columns:
            players_view.insert(0, "Poradie", range(1, len(players_view) + 1))

    # Tab-navigácia
    tab_prehlad, tab_hrac, tab_export = st.tabs(["Prehľad", "Hráč", "Export"])

    # --------------------------------------------------------
    # Tab 1: Prehľad (kompaktný mobilný výhľad + plná tabuľka v expanderi)
    # --------------------------------------------------------
    with tab_prehlad:
        st.subheader("Zoznam hráčov (rešpektuje výber rokov a formátov)")
        if players_view.empty:
            st.info("Pre zvolené filtre nie sú k dispozícii žiadni hráči.")
        else:
            # pred zobrazením formátuj *Body* na 1/0.5
            disp = players_view.copy()
            for c in [c for c in disp.columns if c.endswith("Body")]:
                disp[c] = disp[c].map(_fmt_points)

            if mobile_mode:
                # Kompaktná tabuľka (kľúčové stĺpce)
                keep_cols = [c for c in [
                    "Poradie", "Hráč", "Team",
                    "Spolu Body", "Spolu Zápasy", "Spolu Úspešnosť",
                    "Single Body", "Single Úspešnosť",
                ] if c in disp.columns]
                # Skrátené hlavičky
                rename_map = {
                    "Team": "Tím", "Spolu Zápasy": "Záp.", "Spolu Úspešnosť": "Úsp.",
                    "Single Body": "1v1 Body", "Single Úspešnosť": "1v1 Úsp.",
                }
                mobile_tbl = disp[keep_cols].rename(columns={k: v for k, v in rename_map.items() if k in keep_cols})
                st.dataframe(mobile_tbl, use_container_width=True, hide_index=True)

                with st.expander("Zobraziť plnú tabuľku"):
                    st.dataframe(disp, use_container_width=True, hide_index=True)
            else:
                st.dataframe(disp, use_container_width=True, hide_index=True)

		# --- Výber hráča (presunutý sem z tabu Hráč) ---
        st.markdown("### Výber hráča")
        player_options = sorted([p for p in players_view["Hráč"].tolist()] if not players_view.empty else [], key=sk_sort_key)

        # ak už je niečo v session_state (z predchádzajúceho výberu), predvoľ ho
        prev_player = st.session_state.get("selected_player", None)
        default_index = player_options.index(prev_player) if (prev_player in player_options) else (0 if player_options else None)

        selected_player = st.selectbox(
            "Hráč",
            options=player_options if player_options else ["—"],
            index=default_index,
            key="selected_player"  # kľúč ostáva rovnaký, aby ho tab Hráč vedel použiť
        )
				
				
        st.caption(
            f"Roky: {', '.join(map(str, selected_years_list)) if selected_years_list else '—'} • "
            f"Formáty: {', '.join(fmt_selected) if fmt_selected else '—'} • "
            f"Team: {', '.join(sorted(list(selected_team_set))) if selected_team_set else '—'} • "
            f"Zoradenie: {sort_col}"
        )

    # --------------------------------------------------------
    # Tab 2: Hráč (detail a súhrny)
    # --------------------------------------------------------
        
	with tab_hrac:
        st.subheader("Detail hráča")
        selected_player = st.session_state.get("selected_player")

        if not selected_player or selected_player == "—":
            st.info("Hráča vyber v záložke **Prehľad** pod tabuľkou „Zoznam hráčov“.")
        else:
            # --- Ponechaj svoj doterajší kód na spracovanie vybraného hráča ---
            # (od vyfiltrovania df_player, cez dfp, df_fmt_sum, df_year_sum,
            #  až po zobrazenie výsledkov a súhrnov)
            # Začiatok pôvodného bloku:
            df_player = df.copy()
            mask = False
            for col in ["L1", "L2", "R1", "R2"]:
                if col in df_player.columns:
                    mask = mask | df_player[col].fillna("").astype(str).str.casefold().str.contains(selected_player.casefold())
            df_player = df_player[mask]
            if selected_years_list and "Rok" in df_player.columns:
                df_player = df_player[df_player["Rok"].isin(selected_years_list)]
            if fmt_selected and "Formát" in df_player.columns:
                df_player = df_player[df_player["Formát"].isin(fmt_selected)]

            if "Formát" in df_player.columns:
                single_mask = df_player["Formát"].astype(str) == "Single"
                for col in ["L2", "R2"]:
                    if col in df_player.columns:
                        df_player.loc[single_mask, col] = df_player.loc[single_mask, col].apply(
                            lambda x: "" if (pd.isna(x) or str(x).strip().lower() in {"", "nan", "none", "null"}) else str(x).strip()
                        )

            if "Rok" in df_player.columns:
                df_player["Rezort"] = df_player["Rok"].map(tourn_map).fillna("")

            dfp = df_player.copy().drop(columns=[c for c in ["L1", "L2", "R1", "R2"] if c in df_player.columns], errors="ignore")
            if "Rok" in dfp.columns and "Rezort" in dfp.columns:
                cols = dfp.columns.tolist()
                cols.remove("Rezort")
                idx = cols.index("Rok") + 1
                cols.insert(idx, "Rezort")
                dfp = dfp[cols]
            if "Deň" in dfp.columns:
                dfp["Deň"] = pd.to_numeric(dfp["Deň"], errors="coerce").apply(lambda x: "" if pd.isna(x) else f"{int(x)}")
            for col in ["Lbody", "Rbody"]:
                if col in dfp.columns:
                    dfp[col] = pd.to_numeric(dfp[col], errors="coerce").map(lambda v: "" if pd.isna(v) else _fmt_points(float(v)))

            df_fmt_sum, df_year_sum = _summaries_for_player(df_player, selected_player, tourn_map)

            st.subheader(f"Výsledky hráča: {selected_player}")
            st.dataframe(dfp.reset_index(drop=True), use_container_width=True, hide_index=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Súhrn podľa formátu**")
                if df_fmt_sum.empty:
                    st.info("Žiadne zápasy pre zvolené filtre.")
                else:
                    st.dataframe(df_fmt_sum[["Formát", "Body", "Zápasy", "Úspešnosť"]],
                                 use_container_width=True, hide_index=True)
            with c2:
                st.markdown("**Súhrn podľa roku**")
                if df_year_sum.empty:
                    st.info("Žiadne zápasy pre zvolené filtre.")
                else:
                    st.dataframe(df_year_sum[["Rok", "Rezort", "Body", "Zápasy", "Úspešnosť"]],
                                 use_container_width=True, hide_index=True)
		
		
		if selected_player and selected_player != "—":
            # Vyfiltrované zápasy daného hráča (v rámci vybraných rokov a formátov)
            df_player = df.copy()
            mask = False
            for col in ["L1", "L2", "R1", "R2"]:
                if col in df_player.columns:
                    mask = mask | df_player[col].fillna("").astype(str).str.casefold().str.contains(selected_player.casefold())
            df_player = df_player[mask]
            if selected_years_list and "Rok" in df_player.columns:
                df_player = df_player[df_player["Rok"].isin(selected_years_list)]
            if fmt_selected and "Formát" in df_player.columns:
                df_player = df_player[df_player["Formát"].isin(fmt_selected)]

            # Single: prázdne L2/R2
            if "Formát" in df_player.columns:
                single_mask = df_player["Formát"].astype(str) == "Single"
                for col in ["L2", "R2"]:
                    if col in df_player.columns:
                        df_player.loc[single_mask, col] = df_player.loc[single_mask, col].apply(
                            lambda x: "" if (pd.isna(x) or str(x).strip().lower() in {"", "nan", "none", "null"}) else str(x).strip()
                        )

            # Doplň "Rezort" podľa "Rok"
            if "Rok" in df_player.columns:
                df_player["Rezort"] = df_player["Rok"].map(tourn_map).fillna("")

            # Display verzia (skryť L1/L2/R1/R2 + formátovať čísla)
            dfp = df_player.copy().drop(columns=[c for c in ["L1", "L2", "R1", "R2"] if c in df_player.columns], errors="ignore")
            if "Rok" in dfp.columns and "Rezort" in dfp.columns:
                cols = dfp.columns.tolist()
                cols.remove("Rezort")
                idx = cols.index("Rok") + 1
                cols.insert(idx, "Rezort")
                dfp = dfp[cols]
            if "Deň" in dfp.columns:
                dfp["Deň"] = pd.to_numeric(dfp["Deň"], errors="coerce").apply(lambda x: "" if pd.isna(x) else f"{int(x)}")
            for col in ["Lbody", "Rbody"]:
                if col in dfp.columns:
                    dfp[col] = pd.to_numeric(dfp[col], errors="coerce").map(lambda v: "" if pd.isna(v) else _fmt_points(float(v)))

            # Súhrny (formát / rok)
            df_fmt_sum, df_year_sum = _summaries_for_player(df_player, selected_player, tourn_map)

            # Zobrazenie
            st.subheader(f"Výsledky hráča: {selected_player}")
            st.dataframe(dfp.reset_index(drop=True), use_container_width=True, hide_index=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Súhrn podľa formátu**")
                if df_fmt_sum.empty:
                    st.info("Žiadne zápasy pre zvolené filtre.")
                else:
                    st.dataframe(df_fmt_sum[["Formát", "Body", "Zápasy", "Úspešnosť"]],
                                 use_container_width=True, hide_index=True)
            with c2:
                st.markdown("**Súhrn podľa roku**")
                if df_year_sum.empty:
                    st.info("Žiadne zápasy pre zvolené filtre.")
                else:
                    st.dataframe(df_year_sum[["Rok", "Rezort", "Body", "Zápasy", "Úspešnosť"]],
                                 use_container_width=True, hide_index=True)
        else:
            st.info("Vyber hráča zo zoznamu vyššie.")

    # --------------------------------------------------------
    # Tab 3: Export (Excel report s viacerými listami)
    # --------------------------------------------------------
    with tab_export:
        st.subheader("Export (Excel)")

        xls_report = BytesIO()
        with pd.ExcelWriter(xls_report, engine="openpyxl") as xw:
            wb = xw.book  # openpyxl workbook

            # 1) Zoznam hráčov (aktuálny výber)
            export_cols = [
                "Poradie", "Hráč", "Team",
                "Foursome Body", "Foursome Zápasy", "Foursome Úspešnosť",
                "Fourball Body", "Fourball Zápasy", "Fourball Úspešnosť",
                "Single Body", "Single Zápasy", "Single Úspešnosť",
                "Spolu Body", "Spolu Zápasy", "Spolu Úspešnosť",
            ]
            if not players_view.empty:
                players_xls_df = players_view[export_cols].copy()
                percent_cols_players = ["Foursome Úspešnosť", "Fourball Úspešnosť", "Single Úspešnosť", "Spolu Úspešnosť"]
                for c in percent_cols_players:
                    if c in players_xls_df.columns:
                        players_xls_df[c] = (
                            players_xls_df[c].astype(str).str.replace("%", "", regex=False).replace("", "0").astype(float) / 100.0
                        )
                players_xls_df.to_excel(xw, sheet_name="Zoznam hráčov", index=False)
                ws = wb["Zoznam hráčov"]
                _excel_center_and_bold(ws)
                _excel_set_percent_format(ws, percent_cols_players)
                _excel_set_col_widths(ws, {
                    "Poradie": 8, "Hráč": 24, "Team": 12,
                    "Foursome Body": 12, "Foursome Zápasy": 12, "Foursome Úspešnosť": 14,
                    "Fourball Body": 12, "Fourball Zápasy": 12, "Fourball Úspešnosť": 14,
                    "Single Body": 12, "Single Zápasy": 12, "Single Úspešnosť": 14,
                    "Spolu Body": 12, "Spolu Zápasy": 12, "Spolu Úspešnosť": 14,
                })
            else:
                pd.DataFrame(columns=export_cols).to_excel(xw, sheet_name="Zoznam hráčov", index=False)
                ws = wb["Zoznam hráčov"]
                _excel_center_and_bold(ws)
                _excel_set_col_widths(ws, {
                    "Poradie": 8, "Hráč": 24, "Team": 12,
                    "Foursome Body": 12, "Foursome Zápasy": 12, "Foursome Úspešnosť": 14,
                    "Fourball Body": 12, "Fourball Zápasy": 12, "Fourball Úspešnosť": 14,
                    "Single Body": 12, "Single Zápasy": 12, "Single Úspešnosť": 14,
                    "Spolu Body": 12, "Spolu Zápasy": 12, "Spolu Úspešnosť": 14,
                })

            # 2) Ak je vybraný hráč v stave, vygeneruj jeho listy
            selected_player = st.session_state.get("selected_player")
            if selected_player and selected_player != "—":
                # znovu prepočítaj pre export (rovnaká logika ako v tabu Hráč)
                df_player = df.copy()
                mask = False
                for col in ["L1", "L2", "R1", "R2"]:
                    if col in df_player.columns:
                        mask = mask | df_player[col].fillna("").astype(str).str.casefold().str.contains(selected_player.casefold())
                df_player = df_player[mask]
                if selected_years_list and "Rok" in df_player.columns:
                    df_player = df_player[df_player["Rok"].isin(selected_years_list)]
                if fmt_selected and "Formát" in df_player.columns:
                    df_player = df_player[df_player["Formát"].isin(fmt_selected)]

                if "Formát" in df_player.columns:
                    single_mask = df_player["Formát"].astype(str) == "Single"
                    for col in ["L2", "R2"]:
                        if col in df_player.columns:
                            df_player.loc[single_mask, col] = df_player.loc[single_mask, col].apply(
                                lambda x: "" if (pd.isna(x) or str(x).strip().lower() in {"", "nan", "none", "null"}) else str(x).strip()
                            )

                if "Rok" in df_player.columns:
                    df_player["Rezort"] = df_player["Rok"].map(tourn_map).fillna("")

                dfp = df_player.copy().drop(columns=[c for c in ["L1", "L2", "R1", "R2"] if c in df_player.columns], errors="ignore")
                if "Rok" in dfp.columns and "Rezort" in dfp.columns:
                    cols = dfp.columns.tolist()
                    cols.remove("Rezort")
                    idx = cols.index("Rok") + 1
                    cols.insert(idx, "Rezort")
                    dfp = dfp[cols]
                if "Deň" in dfp.columns:
                    dfp["Deň"] = pd.to_numeric(dfp["Deň"], errors="coerce").apply(lambda x: "" if pd.isna(x) else f"{int(x)}")
                for col in ["Lbody", "Rbody"]:
                    if col in dfp.columns:
                        dfp[col] = pd.to_numeric(dfp[col], errors="coerce").map(lambda v: "" if pd.isna(v) else _fmt_points(float(v)))

                df_fmt_sum, df_year_sum = _summaries_for_player(df_player, selected_player, tourn_map)

                # Zápasy hráča
                safe_name = f"Zápasy – {selected_player}"
                safe_name = safe_name[:31]  # limit excelového názvu listu
                dfp.to_excel(xw, sheet_name=safe_name, index=False)
                ws = wb[safe_name]
                _excel_center_and_bold(ws)
                _excel_set_col_widths(ws, {"Rok": 8, "Rezort": 20, "Deň": 8, "Zápas": 8, "Formát": 12, "Lbody": 10, "Rbody": 10, "Víťaz": 10})

                # Súhrn podľa formátu
                if not df_fmt_sum.empty:
                    df_fmt_xls = df_fmt_sum.copy()
                    if "Úspešnosť" in df_fmt_xls.columns:
                        df_fmt_xls["Úspešnosť"] = df_fmt_xls["Úspešnosť"].astype(str).str.replace("%", "", regex=False).replace("", "0").astype(float) / 100.0
                    df_fmt_xls.to_excel(xw, sheet_name="Súhrn podľa formátu", index=False)
                    ws = wb["Súhrn podľa formátu"]
                    _excel_center_and_bold(ws)
                    _excel_set_percent_format(ws, ["Úspešnosť"])
                    _excel_set_col_widths(ws, {"Formát": 16, "Body": 12, "Zápasy": 10, "Úspešnosť": 12})

                # Súhrn podľa roku
                if not df_year_sum.empty:
                    df_year_xls = df_year_sum.copy()
                    if "Úspešnosť" in df_year_xls.columns:
                        df_year_xls["Úspešnosť"] = df_year_xls["Úspešnosť"].astype(str).str.replace("%", "", regex=False).replace("", "0").astype(float) / 100.0
                    df_year_xls.to_excel(xw, sheet_name="Súhrn podľa roku", index=False)
                    ws = wb["Súhrn podľa roku"]
                    _excel_center_and_bold(ws)
                    _excel_set_percent_format(ws, ["Úspešnosť"])
                    _excel_set_col_widths(ws, {"Rok": 8, "Rezort": 20, "Body": 12, "Zápasy": 10, "Úspešnosť": 12})

            # 3) Filtre (pre transparentnosť exportu)
            filters_df = pd.DataFrame({
                "Filter": ["Roky", "Formáty", "Team", "Zoradenie"],
                "Hodnota": [
                    ", ".join(map(str, selected_years_list)) if selected_years_list else "—",
                    ", ".join(fmt_selected) if fmt_selected else "—",
                    ", ".join(sorted(list(selected_team_set))) if selected_team_set else "—",
                    sort_col,
                ],
            })
            filters_df.to_excel(xw, sheet_name="Filtre", index=False)
            ws = wb["Filtre"]
            _excel_center_and_bold(ws)
            _excel_set_col_widths(ws, {"Filter": 16, "Hodnota": 50})

        st.download_button(
            label="Stiahnuť report (Excel)",
            data=xls_report.getvalue(),
            file_name="LeftiesRighties_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_full_report_xlsx",
        )


if __name__ == "__main__":
    main()