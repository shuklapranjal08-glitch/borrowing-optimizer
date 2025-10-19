import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date
from dateutil import parser

st.set_page_config(page_title="Borrowing Optimiser", page_icon="💸", layout="wide")
st.title("💸 Borrowing Optimiser")
st.write("Upload your Excel (and optionally paste mail text) to get the optimal draw order.")

DATE_COL_CANDIDATES = ["Date of availability", "Availability Date", "Available On", "Availability"]
ROI_COL_CANDIDATES = ["ROI", "Interest", "Rate", "Rate of Interest"]
AMOUNT_COL_CANDIDATES = ["Amount to be drawn", "Amount", "Draw Amount", "Available Amount"]
TENOR_COL_CANDIDATES = ["Tenor", "Tenure", "Term"]
TYPE_COL_CANDIDATES = ["Type", "Loan Type"]

NEAR_WINDOW_DAYS = st.number_input("Near-availability window (days)", min_value=1, max_value=30, value=10)

def read_excel(file) -> pd.DataFrame:
    try:
        return pd.read_excel(file)
    except Exception as e:
        st.error(f"Could not read Excel: {e}")
        return pd.DataFrame()

def smart_pick_col(df: pd.DataFrame, candidates):
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        for c in cols:
            if cand.lower() == c:
                return cols[c]
    for cand in candidates:
        for c in cols:
            if cand.lower() in c:
                return cols[c]
    return None

def coerce_date(x):
    if pd.isna(x):
        return pd.NaT
    if isinstance(x, (datetime, date)):
        return pd.to_datetime(x)
    try:
        return pd.to_datetime(parser.parse(str(x), dayfirst=True, fuzzy=True))
    except Exception:
        return pd.NaT

def normalise_types(val):
    if pd.isna(val):
        return np.nan
    s = str(val).strip().lower()
    if s in ("st", "short", "short-term", "short term"):
        return "ST"
    if s in ("lt", "long", "long-term", "long term"):
        return "LT"
    return val

with st.sidebar:
    st.header("📌 Draw Target (optional)")
    target_amount = st.number_input("Total amount you want to draw now", min_value=0.0, value=0.0, step=1.0)
    st.caption("If set, we'll show how many lines you need (in order) to meet this amount.")

excel_file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"]) 
mail_text = st.text_area("Paste mail body (optional)")

if excel_file is None:
    st.info("Upload an Excel to begin. Columns can be named flexibly — we'll auto-detect.")
    st.stop()

raw = read_excel(excel_file)
if raw.empty:
    st.stop()

map_cols = {}
map_cols['date'] = smart_pick_col(raw, DATE_COL_CANDIDATES)
map_cols['roi'] = smart_pick_col(raw, ROI_COL_CANDIDATES)
map_cols['amount'] = smart_pick_col(raw, AMOUNT_COL_CANDIDATES)
map_cols['tenor'] = smart_pick_col(raw, TENOR_COL_CANDID
