import pandas as pd
import streamlit as st
import re
from collections import defaultdict
from typing import List, Dict, Tuple
from urllib.parse import quote
from io import BytesIO  # Excel export

# openpyxl na formátovanie Excelu
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

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
    s = s.strip().lower()
    if not s:
        return []
    s = _CH_RE.sub(_PLACEHOLDER, s)
    tokens = []
    for ch in s:
        tokens.append("ch" if ch == _PLACEHOLDER else ch)
    return [t for t in tokens if t in _SK_INDEX]


def sk_sort_key(name: str):
    if not isinstance(name, str):
        name = "" if pd.isna(name) else str(name)
    tokens = _tokenize_sk(name)
    if not tokens:
        return (len(_SK_ORDER) + 1,)
    return tuple(_SK_INDEX[t] for t in tokens)


# ------------------------------------------------------------
# Načítanie, čistenie dát
# ------------------------------------------------------------
@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    """Načíta hlavné dáta (Zápasy)."""
    df = pd.read_excel(path, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    # Číselné
    for col in ["Rok", "Deň", "Zápas", "Lbody", "Rbody"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Textové
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip()
    # Zoradenie
    if {"Rok", "Deň", "Zápas"}.issubset(df.columns):
        df = df.sort_values(["Rok", "Deň", "Zápas"], ascending=[True, True, True])
    return df


@st.cache_data
def load_tournaments(path: str) -> pd.DataFrame:
    """
    Načíta záložku 'Turnaje' – prvé dva stĺpce:
    'Turnaje' -> 'Rok' (int) a 'Ihrisko' -> 'Rezort'.
    """
    try:
        t = pd.read_excel(path, sheet_name="Turnaje", engine="openpyxl")
    except Exception:
        t = pd.read_excel(path, sheet_name=1, engine="openpyxl")  # fallback
    t.columns = [str(c).strip() for c in t.columns]
    col_year = "Turnaje" if "Turnaje" in t.columns else t.columns[0]
    col_resort = "Ihrisko" if "Ihrisko" in t.columns else t.columns[1]
    out = t[[col_year, col_resort]].copy()
    out = out.rename(columns={col_year: "Rok", col_resort: "Rezort"})
    out["Rok"] = pd.to_numeric(out["Rok"], errors="coerce").astype("Int64")
    out = out.dropna(subset=["Rok"]).astype({"Rok": int})
    out = out.sort_values("Rok").reset_index(drop=True)
    return out


def _norm_name(x) -> str:
    """Normalizuje meno (''/nan/none/null → '')."""
    s = "" if pd.isna(x) else str(x).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return ""
    return s


# ------------------------------------------------------------
# Štatistiky (po formátoch / spolu)
# ------------------------------------------------------------
def _series_from_cols(df: pd.DataFrame, cols: List[str]) -> pd.Series:
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return pd.Series(dtype="object")
    s = pd.concat([df[c] for c in cols], ignore_index=True).map(_norm_name)
    return s[s != ""]


def _compute_player_points(d: pd.DataFrame) -> Dict[str, float]:
    """
    Body:
      - hráč v L1/L2 -> Lbody
      - hráč v R1/R2 -> Rbody
      (prázdne L2/R2 ignorovať)
    """
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
    """Numerická úspešnosť v percentách (0–100)."""
    return 0.0 if zapasy <= 0 else (body / zapasy) * 100.0


def _fmt_points(x: float) -> str:
    """Body: celé číslo; ak .5, zobraz 1 desatinné (napr. 1.5)."""
    if pd.isna(x):
        return ""
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x))}"
    if abs((x * 2) - round(x * 2)) < 1e-9 and int(round(x * 2)) % 2 == 1:
        return f"{x:.1f}"
    return f"{int(round(x))}"


@st.cache_data
def players_summary(df: pd.DataFrame, years: List[int] = None, formats: List[str] = None) -> pd.DataFrame:
    """Tabuľka hráčov s metrikami (rešpektuje Rok a Formát)."""
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
            key=lambda col: (
                col.map({"Lefties": 0, "Righties": 1, "Oboje": 2}) if col.name == "Team"
                else col.map(sk_sort_key)
            ),
        ).reset_index(drop=True)
    return out


# ------------------------------------------------------------
# Callbacky pre Turnaje
# ------------------------------------------------------------
def _toggle_all_tournaments():
    """Prepne všetky roky podľa 'Všetky turnaje' a nechá Streamlit prerunúť."""
    years = st.session_state.get("_years_desc", [])
    all_on = st.session_state.get("chk_all_tourn", False)
    for yr in years:
        st.session_state[f"chk_year_{yr}"] = all_on
    # Po callbacku Streamlit automaticky prerunuje.


def _sync_master_from_children():
    """Keď sa zmení ktorýkoľvek rok, zosynchronizuje master 'Všetky turnaje'."""
    years = st.session_state.get("_years_desc", [])
    if not years:
        st.session_state["chk_all_tourn"] = False
        return
    all_on = all(st.session_state.get(f"chk_year_{yr}", False) for yr in years)
    st.session_state["chk_all_tourn"] = all_on


# ------------------------------------------------------------
# Pomocné: Excel formátovanie (percentá, šírky, tučné hlavičky, centrovanie)
# ------------------------------------------------------------
def _excel_center_and_bold(ws):
    """Centrovanie všetkých buniek a tučná hlavička (1. riadok)."""
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
    """Šírky stĺpcov podľa názvov hlavičiek."""
    # map: názov -> index
    header_map = {cell.value: idx+1 for idx, cell in enumerate(ws[1])}
    for name, width in widths.items():
        if name in header_map:
            col_letter = get_column_letter(header_map[name])
            ws.column_dimensions[col_letter].width = float(width)


def _excel_set_percent_format(ws, percent_headers: List[str]):
    """Nastaví number_format '0%' pre všetky bunky v stĺpcoch percent_headers (od riadku 2)."""
    header_map = {cell.value: idx+1 for idx, cell in enumerate(ws[1])}
    for name in percent_headers:
        if name in header_map:
            col_idx = header_map[name]
            for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
                for cell in row:
                    cell.number_format = "0%"


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------
def main():
    st.set_page_config(page_title="Lefties & Righties", layout="wide")
    st.title("Lefties & Righties")

    df = load_data(EXCEL_PATH)
    tourn = load_tournaments(EXCEL_PATH)

    # mapovanie rok -> rezort
    tourn_map = dict(zip(tourn["Rok"], tourn["Rezort"]))

    # ---------- Globálny CSS: kompaktné medzery + centrovanie buniek + sticky head ----------
    st.markdown("""
    <style>
      /* Sidebar – kompaktné medzery pri checkboxoch, radiách a selectboxoch */
      [data-testid="stSidebar"] .stCheckbox,
      [data-testid="stSidebar"] .stRadio,
      [data-testid="stSidebar"] .stSelectbox {
          margin: 0.06rem 0 !important;
      }
      [data-testid="stSidebar"] .stCheckbox > label,
      [data-testid="stSidebar"] .stRadio > div[role="radiogroup"] label {
          margin-bottom: 0.02rem !important;
      }

      /* Všetky DataFrame – centrovanie buniek a sticky hlavička */
      [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th { text-align: center !important; }
      [data-testid="stDataFrame"] td p, [data-testid="stDataFrame"] th p { text-align: center !important; margin: 0; }
      [data-testid="stDataFrame"] thead tr th {
        position: sticky; top: 0; z-index: 2; background: var(--background-color);
      }
    </style>
    """, unsafe_allow_html=True)

    # ---------------- SIDEBAR – filtre ----------------
    st.sidebar.header("Filtre")

    # ---- Turnaje (Roky) – master + scroll box (~5 položiek) ----
    st.sidebar.subheader("Turnaje")

    years_asc = tourn["Rok"].tolist()
    resorts_asc = tourn["Rezort"].tolist()
    max_year = max(years_asc) if years_asc else None

    # poradie zhora: posledný -> prvý
    years_desc = years_asc[::-1]
    resorts_desc = resorts_asc[::-1]
    st.session_state["_years_desc"] = years_desc  # pre callbacky

    # master
    st.sidebar.checkbox(
        "Všetky turnaje",
        value=False,
        key="chk_all_tourn",
        on_change=_toggle_all_tournaments,
        help="Zaškrtne/odškrtne všetky roky",
    )

    # Scroll box – výška približne na 5 položiek
    st.sidebar.markdown(
        '<div style="max-height: 180px; overflow-y: auto; padding-right: 6px; margin-top: 0;">',
        unsafe_allow_html=True
    )

    selected_years_list: List[int] = []
    for yr, rez in zip(years_desc, resorts_desc):
        key = f"chk_year_{yr}"
        # default: ak ešte nie je stav, nastav len posledný (najvyšší) rok
        if key not in st.session_state:
            st.session_state[key] = (yr == max_year)
        val = st.sidebar.checkbox(f"{yr} – {rez}", key=key, on_change=_sync_master_from_children)
        if val:
            selected_years_list.append(int(yr))

    st.sidebar.markdown('</div>', unsafe_allow_html=True)

    # ---- Formát (checklist) ----
    st.sidebar.subheader("Formát")
    fmt_options = ["Foursome", "Fourball", "Single"]
    fmt_selected = []
    for fmt in fmt_options:
        k = f"fmt_{fmt}"
        v = st.sidebar.checkbox(fmt, value=True, key=k)
        if v:
            fmt_selected.append(fmt)

    # ---- Team (checklist: Lefties, Righties) ----
    st.sidebar.subheader("Team")
    team_left = st.sidebar.checkbox("Lefties", value=True, key="team_left")
    team_right = st.sidebar.checkbox("Righties", value=True, key="team_right")
    selected_team_set = set()
    if team_left:
        selected_team_set.add("Lefties")
    if team_right:
        selected_team_set.add("Righties")

    # ---- Zoradiť podľa (radio) ----
    st.sidebar.markdown("**Zoradiť podľa**")
    sort_col = st.sidebar.radio(
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
        index=0,  # implicitne podľa mena
        key="sort_radio",
    )

    # ---------------- ZOZNAM HRÁČOV ----------------
    st.subheader("Zoznam hráčov (rešpektuje výber rokov aj formátov)")

    # žiadny turnaj vybraný -> prázdna tabuľka (bez padovania do dát)
    if selected_years_list:
        players_all = players_summary(df, selected_years_list, fmt_selected)
    else:
        players_all = pd.DataFrame()

    # Filter Team
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

    # Triedenie podľa voľby (dvojkľúče pre Body/Zápasy/Úspešnosť; formáty majú vlastné usp_num stĺpce)
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

    # Poradie + zobrazenie
    if not players_view.empty:
        players_view = players_view.reset_index(drop=True)
        players_view.insert(0, "Poradie", range(1, len(players_view) + 1))

        base_cols_order = [
            "Poradie", "Hráč", "Team",
            "Foursome Body", "Foursome Zápasy", "Foursome Úspešnosť",
            "Fourball Body", "Fourball Zápasy", "Fourball Úspešnosť",
            "Single Body", "Single Zápasy", "Single Úspešnosť",
            "Spolu Body", "Spolu Zápasy", "Spolu Úspešnosť",
        ]
        tbl = players_view[base_cols_order].copy()
        for c in [c for c in tbl.columns if c.endswith("Body")]:
            tbl[c] = tbl[c].map(_fmt_points)

        header_tuples = [
            ("", "Poradie"), ("", "Hráč"), ("", "Team"),
            ("Foursome", "Body"), ("Foursome", "Zápasy"), ("Foursome", "Úspešnosť"),
            ("Fourball", "Body"), ("Fourball", "Zápasy"), ("Fourball", "Úspešnosť"),
            ("Single", "Body"), ("Single", "Zápasy"), ("Single", "Úspešnosť"),
            ("Spolu", "Body"), ("Spolu", "Zápasy"), ("Spolu", "Úspešnosť"),
        ]
        tbl.columns = pd.MultiIndex.from_tuples(header_tuples)

        # len vizuálne padovanie (ak má aspoň 1 riadok)
        if len(tbl) < 12 and len(tbl) > 0:
            pad = 12 - len(tbl)
            blank_row = pd.DataFrame([["" for _ in range(len(tbl.columns))]], columns=tbl.columns)
            tbl = pd.concat([tbl, pd.concat([blank_row] * pad, ignore_index=True)], ignore_index=True)

        # farbenie podľa Team
        def row_colorizer(row: pd.Series):
            team = row.get(("", "Team"), "")
            if team == "Lefties":
                return ["background-color: #e6f3ff; text-align: center;"] * len(row)
            if team == "Righties":
                return ["background-color: #ffeaea; text-align: center;"] * len(row)
            return ["text-align: center;"] * len(row)

        styler_players = (
            tbl.style
            .apply(row_colorizer, axis=1)
            .set_table_styles([
                {"selector": "th", "props": [("font-weight", "bold"), ("text-align", "center"), ("white-space", "pre-line")]},
                {"selector": "td", "props": [("text-align", "center")]},
            ])
            .set_properties(**{"text-align": "center"})
            .set_table_styles([
                {"selector": "td p", "props": [("margin", "0"), ("text-align", "center")]},
                {"selector": "th p", "props": [("margin", "0"), ("text-align", "center")]},
            ], overwrite=False)
        )

        st.dataframe(styler_players, use_container_width=True, hide_index=True)

        st.caption(
            f"Roky: {', '.join(map(str, selected_years_list)) if selected_years_list else '—'} • "
            f"Formáty: {', '.join(fmt_selected) if fmt_selected else '—'} • "
            f"Team: {', '.join(sorted(list(selected_team_set))) if selected_team_set else '—'} • "
            f"Zoradenie: {sort_col}"
        )
    else:
        st.info("Pre zvolené filtre nie sú k dispozícii žiadni hráči.")

    st.divider()

    # ---------------- Výber hráča (abecedne vzostupne) ----------------
    st.sidebar.subheader("Výber hráča")
    player_options = sorted([p for p in players_view["Hráč"].tolist()] if not players_view.empty else [], key=sk_sort_key)
    selected_player = st.sidebar.selectbox(
        "Hráč",
        options=player_options if player_options else ["—"],
        index=None if player_options else 0,
        help="Zoznam je obmedzený aktuálnymi filtrami (rok/formát/team) a je vždy zoradený abecedne."
    )

    # ---------------- Výsledky hráča + súhrny ----------------
    dfp = None
    df_fmt_sum = pd.DataFrame()
    df_year_sum = pd.DataFrame()

    if selected_player and selected_player != "—":
        # --- určenie teamu pre titulok ---
        team_for_title = None
        try:
            if "players_view" in locals() and isinstance(players_view, pd.DataFrame) and not players_view.empty:
                row = players_view.loc[players_view["Hráč"] == selected_player, "Team"]
                if not row.empty:
                    team_for_title = str(row.iloc[0]).strip() or None
        except Exception:
            team_for_title = None

        if team_for_title is None:
            # Fallback z celého datasetu (výskyt v L1/L2 ― Lefties, v R1/R2 ― Righties, v oboch ― Oboje)
            left_cols = [c for c in ["L1", "L2"] if c in df.columns]
            right_cols = [c for c in ["R1", "R2"] if c in df.columns]
            in_left = pd.concat([df[c] for c in left_cols], axis=0).astype(str).str.casefold().str.contains(selected_player.casefold()).any() if left_cols else False
            in_right = pd.concat([df[c] for c in right_cols], axis=0).astype(str).str.casefold().str.contains(selected_player.casefold()).any() if right_cols else False
            team_for_title = "Oboje" if (in_left and in_right) else ("Lefties" if in_left else ("Righties" if in_right else ""))

        title_suffix = f" ({team_for_title})" if team_for_title else ""
        st.subheader(f"Výsledky hráča: {selected_player}{title_suffix}")

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

        # ********** DOPLNENIE 'Rezort' podľa 'Rok' **********
        if "Rok" in df_player.columns:
            df_player["Rezort"] = df_player["Rok"].map(tourn_map).fillna("")

        # Zobrazenie: skryť L1/L2/R1/R2 + pridať 'Rezort' za 'Rok' + formát Deň/Lbody/Rbody
        dfp = df_player.copy().drop(columns=[c for c in ["L1", "L2", "R1", "R2"] if c in df_player.columns], errors="ignore")

        # presuň 'Rezort' hneď za 'Rok'
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

        def _row_color_by_winner(row):
            win = str(row.get("Víťaz", "")).strip()
            if win == "Lefties":
                return ["background-color: #e6f3ff; text-align: center;"] * len(row)
            if win == "Righties":
                return ["background-color: #ffeaea; text-align: center;"] * len(row)
            return ["text-align: center;"] * len(row)

        styled_player = (
            dfp.reset_index(drop=True)
               .style
               .apply(_row_color_by_winner, axis=1)
               .set_table_styles([
                   {"selector": "th", "props": [("text-align", "center"), ("font-weight", "bold")]},
                   {"selector": "td", "props": [("text-align", "center")]},
                   {"selector": "td p", "props": [("margin", "0"), ("text-align", "center")]},
                   {"selector": "th p", "props": [("margin", "0"), ("text-align", "center")]},
               ])
        )
        st.dataframe(styled_player, use_container_width=True, hide_index=True)

        # Súhrny (formát/rok) – numeric intermezzo + display + Spolu
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
                    on_left  = (player.casefold() in L1.casefold()) or (player and player.casefold() in L2.casefold())
                    on_right = (player.casefold() in R1.casefold()) or (player and player.casefold() in R2.casefold())
                    if on_left or on_right:
                        matches += 1
                        if on_left:  pts += Lb
                        if on_right: pts += Rb
                return {"Zápasy_num": int(matches), "Body_num": float(pts)}

            # --- podľa formátu (numeric) ---
            fmt_rows = []
            for fmt in ["Foursome", "Fourball", "Single"]:
                sub = d[d["Formát"] == fmt] if "Formát" in d.columns else d.iloc[0:0]
                agg = _accumulate(sub)
                fmt_rows.append({"Formát": fmt, **agg})
            df_fmt_num = pd.DataFrame(fmt_rows)

            # --- podľa roku (numeric) + REZORT ---
            yr_rows = []
            if "Rok" in d.columns:
                for rok, sub in d.groupby("Rok", sort=True):
                    agg = _accumulate(sub)
                    rez = rok_to_rezort.get(int(rok), "")
                    yr_rows.append({"Rok": int(rok), "Rezort": rez, **agg})
            df_year_num = (
                pd.DataFrame(yr_rows).sort_values("Rok")
                if yr_rows else pd.DataFrame(columns=["Rok", "Rezort", "Body_num", "Zápasy_num"])
            )

            # --- display verzie + sumárny riadok ---
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
                    sum_row = {
                        "Rok": "Spolu", "Rezort": "",
                        "Body": _fmt_points(total_body), "Zápasy": total_zap, "Úspešnosť": _success_str(total_body, total_zap)
                    }
                    disp = pd.concat([disp, pd.DataFrame([sum_row])], ignore_index=True)
                    return disp

                # label_col == "Formát"
                disp = pd.DataFrame({
                    "Formát": df_num["Formát"],
                    "Body": df_num["Body_num"].map(_fmt_points),
                    "Zápasy": df_num["Zápasy_num"].astype(int),
                    "Úspešnosť": [_success_str(b, z) for b, z in zip(df_num["Body_num"], df_num["Zápasy_num"])],
                })
                sum_row = {"Formát": "Spolu", "Body": _fmt_points(total_body), "Zápasy": total_zap, "Úspešnosť": _success_str(total_body, total_zap)}
                disp = pd.concat([disp, pd.DataFrame([sum_row])], ignore_index=True)
                return disp

            return _make_display(df_fmt_num, "Formát"), _make_display(df_year_num, "Rok")

        df_fmt_sum, df_year_sum = _summaries_for_player(df_player, selected_player, tourn_map)

        header_gray = "#f0f2f6"

        def _style_with_total(df_disp: pd.DataFrame, label_col: str) -> pd.io.formats.style.Styler:
            def _row_style(row):
                if str(row.get(label_col, "")) == "Spolu":
                    return [f"background-color: {header_gray}; text-align: center; font-weight: 600;"] * len(row)
                return ["text-align: center;"] * len(row)

            return (
                df_disp.reset_index(drop=True)
                      .style
                      .apply(_row_style, axis=1)
                      .set_table_styles([
                          {"selector": "th", "props": [("text-align", "center"), ("font-weight", "bold"), ("background", header_gray)]},
                          {"selector": "td", "props": [("text-align", "center")]},
                      ])
            )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Súhrn podľa formátu**")
            if df_fmt_sum.empty:
                st.info("Žiadne zápasy pre zvolené filtre.")
            else:
                st.dataframe(
                    _style_with_total(df_fmt_sum[["Formát", "Body", "Zápasy", "Úspešnosť"]], "Formát"),
                    use_container_width=True, hide_index=True
                )

        with c2:
            st.markdown("**Súhrn podľa roku**")
            if df_year_sum.empty:
                st.info("Žiadne zápasy pre zvolené filtre.")
            else:
                st.dataframe(
                    _style_with_total(df_year_sum[["Rok", "Rezort", "Body", "Zápasy", "Úspešnosť"]], "Rok"),
                    use_container_width=True, hide_index=True
                )

    # ---------------- Jeden Excel export s viacerými listami + FORMÁTOVANIE ----------------
    # Vždy vytvoríme 'Zoznam hráčov'; ak je zvolený hráč aj jeho 'Zápasy' a 'Súhrny'.
    xls_report = BytesIO()
    with pd.ExcelWriter(xls_report, engine="openpyxl") as xw:
        wb = xw.book  # openpyxl workbook

        # 1) Zoznam hráčov (ak je neprázdny) – konverzia Úspešností na čísla 0..1, aby Excel vedel formátovať %
        export_cols = [
            "Poradie", "Hráč", "Team",
            "Foursome Body", "Foursome Zápasy", "Foursome Úspešnosť",
            "Fourball Body", "Fourball Zápasy", "Fourball Úspešnosť",
            "Single Body", "Single Zápasy", "Single Úspešnosť",
            "Spolu Body", "Spolu Zápasy", "Spolu Úspešnosť",
        ]
        if "players_view" in locals() and isinstance(players_view, pd.DataFrame) and not players_view.empty:
            players_xls_df = players_view[export_cols].copy()
            percent_cols_players = ["Foursome Úspešnosť", "Fourball Úspešnosť", "Single Úspešnosť", "Spolu Úspešnosť"]
            for c in percent_cols_players:
                if c in players_xls_df.columns:
                    players_xls_df[c] = (
                        players_xls_df[c].astype(str).str.replace("%", "", regex=False).replace("", "0").astype(float) / 100.0
                    )
            players_xls_df.to_excel(xw, sheet_name="Zoznam hráčov", index=False)
            ws = wb["Zoznam hráčov"]
            # formátovanie
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

        # 2) Výsledky hráča + Súhrny, ak existujú
        if "dfp" in locals() and isinstance(dfp, pd.DataFrame) and not dfp.empty:
            safe_name = "Zápasy hráča" if "selected_player" not in locals() or not selected_player else f"Zápasy – {selected_player}"
            safe_name = safe_name[:31]
            dfp.to_excel(xw, sheet_name=safe_name, index=False)
            ws = wb[safe_name]
            _excel_center_and_bold(ws)
            # šírky – univerzálne hodnoty pre bežné názvy v zápasoch
            _excel_set_col_widths(ws, {
                "Rok": 8, "Rezort": 20, "Deň": 8, "Zápas": 8,
                "Formát": 12, "Lbody": 10, "Rbody": 10, "Víťaz": 10
            })

        if "df_fmt_sum" in locals() and isinstance(df_fmt_sum, pd.DataFrame) and not df_fmt_sum.empty:
            # percentá -> čísla 0..1
            df_fmt_xls = df_fmt_sum.copy()
            if "Úspešnosť" in df_fmt_xls.columns:
                df_fmt_xls["Úspešnosť"] = df_fmt_xls["Úspešnosť"].astype(str).str.replace("%", "", regex=False).replace("", "0").astype(float) / 100.0
            df_fmt_xls.to_excel(xw, sheet_name="Súhrn podľa formátu", index=False)
            ws = wb["Súhrn podľa formátu"]
            _excel_center_and_bold(ws)
            _excel_set_percent_format(ws, ["Úspešnosť"])
            _excel_set_col_widths(ws, {"Formát": 16, "Body": 12, "Zápasy": 10, "Úspešnosť": 12})

        if "df_year_sum" in locals() and isinstance(df_year_sum, pd.DataFrame) and not df_year_sum.empty:
            df_year_xls = df_year_sum.copy()
            if "Úspešnosť" in df_year_xls.columns:
                df_year_xls["Úspešnosť"] = df_year_xls["Úspešnosť"].astype(str).str.replace("%", "", regex=False).replace("", "0").astype(float) / 100.0
            df_year_xls.to_excel(xw, sheet_name="Súhrn podľa roku", index=False)
            ws = wb["Súhrn podľa roku"]
            _excel_center_and_bold(ws)
            _excel_set_percent_format(ws, ["Úspešnosť"])
            _excel_set_col_widths(ws, {"Rok": 8, "Rezort": 20, "Body": 12, "Zápasy": 10, "Úspešnosť": 12})

        # 3) (Voliteľné) Filtre – pre transparentnosť exportu
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