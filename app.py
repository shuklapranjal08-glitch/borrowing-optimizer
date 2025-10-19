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
map_cols['tenor'] = smart_pick_col(raw, TENOR_COL_CANDIDATES)
map_cols['type'] = smart_pick_col(raw, TYPE_COL_CANDIDATES)

missing = [k for k,v in map_cols.items() if v is None and k in ('date','roi','amount')]
if missing:
    st.error(f"Missing required columns (detected): {', '.join(missing)}. Please rename or add them.")
    with st.expander("Detected columns vs. your sheet"):
        st.write(raw.head())
    st.stop()

df = raw.copy()
df['__date'] = raw[map_cols['date']].apply(coerce_date)
df['__roi'] = pd.to_numeric(raw[map_cols['roi']], errors='coerce')
df['__amount'] = pd.to_numeric(raw[map_cols['amount']], errors='coerce')

if map_cols['type']:
    df['__type'] = raw[map_cols['type']].apply(normalise_types)
else:
    df['__type'] = np.nan

if map_cols['tenor']:
    df['__tenor_days'] = pd.to_numeric(raw[map_cols['tenor']], errors='coerce')
else:
    df['__tenor_days'] = np.nan

today = pd.to_datetime(date.today())
df['__days_to_avail'] = (df['__date'] - today).dt.days
df['__effective_tenor_days'] = np.where(df['__type'].eq('ST') | df['__tenor_days'].isna(), 90, df['__tenor_days'])
df['__near_flag'] = np.select([
    (df['__days_to_avail'] >= 0) & (df['__days_to_avail'] <= NEAR_WINDOW_DAYS),
    (df['__days_to_avail'] < 0)
], [0, 2], default=1)

df_sorted = df.sort_values(by=['__near_flag','__roi','__days_to_avail','__effective_tenor_days'], ascending=[True, True, True, True])

display_cols = []
for label, key in [("Date of availability", 'date'), ("ROI", 'roi'), ("Amount to be drawn", 'amount'), ("Tenor", 'tenor'), ("Type", 'type')]:
    col = map_cols.get(key)
    if col:
        display_cols.append(col)

out = df_sorted.assign(
    **{
        'Availability (days from today)': df_sorted['__days_to_avail'],
        'Near-window? (0 best)': df_sorted['__near_flag'],
        'Effective Tenor (days)': df_sorted['__effective_tenor_days'],
    }
)

plan = None
if target_amount and target_amount > 0:
    remaining = target_amount
    picks = []
    for _, r in out.iterrows():
        amt = r['__amount'] if not np.isnan(r['__amount']) else 0
        if amt <= 0:
            continue
        take = min(amt, remaining)
        picks.append({
            'Picked Amount': take,
            'Remaining After Pick': max(0, remaining - take)
        })
        remaining -= take
        if remaining <= 0:
            break
    if picks:
        plan = pd.concat([out.reset_index(drop=True), pd.DataFrame(picks)], axis=1)

st.subheader("Recommended draw order")
st.dataframe(out[display_cols + ['Availability (days from today)','Near-window? (0 best)','Effective Tenor (days)']].reset_index(drop=True))

if plan is not None:
    st.subheader("Packing plan to meet target amount")
    st.dataframe(plan[display_cols + ['__amount','Picked Amount','Remaining After Pick']].rename(columns={'__amount':'Amount Available'}).reset_index(drop=True))

def to_excel_bytes(df):
    from io import BytesIO
    with pd.ExcelWriter(BytesIO(), engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Borrowing_Order')
        writer.save()
        data = writer.book.save_virtual_workbook()
    return data

col1, col2 = st.columns(2)
with col1:
    st.download_button(
        label="Download order as Excel",
        data=out[display_cols + ['Availability (days from today)','Near-window? (0 best)','Effective Tenor (days)']].to_csv(index=False).encode('utf-8'),
        file_name="borrowing_order.csv",
        mime="text/csv"
    )
with col2:
    st.download_button(
        label="Download full table (CSV)",
        data=out.to_csv(index=False).encode('utf-8'),
        file_name="borrowing_order_full.csv",
        mime="text/csv"
    )

st.caption("Rules: minimize ROI; prefer lines available within the near window; break ties by earlier date and shorter tenor. ST assumed 90 days when tenor missing.")
