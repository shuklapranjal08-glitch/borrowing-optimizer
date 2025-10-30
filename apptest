import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date
from dateutil import parser
from io import BytesIO
from PIL import Image

# Optional (only used when an image is uploaded)
import boto3
import pytz

# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Borrowing Optimiser", page_icon="💸", layout="wide")
st.title("💸 Borrowing Optimiser — Excel or Image Upload")
st.write("Upload an Excel **or** an image of the mail/table. If image is uploaded, we'll use AWS Textract to read it.")

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
DATE_COL_CANDIDATES   = ["Date of availability", "Availability Date", "Available On", "Availability", "Date"]
ROI_COL_CANDIDATES    = ["ROI", "Interest", "Rate", "Rate of Interest"]
AMOUNT_COL_CANDIDATES = ["Amount to be drawn", "Amount", "Draw Amount", "Available Amount", "Amt"]
TENOR_COL_CANDIDATES  = ["Tenor", "Tenure", "Term", "Days"]
TYPE_COL_CANDIDATES   = ["Type", "Loan Type"]

# ALM buckets (30 days/month, 365 days/year approximations)
ALM_BUCKETS = [
    ("0 Days to 7 Days", 0, 7),
    ("8 Days to 14 Days", 8, 14),
    ("15 Days to 30 Days", 15, 30),
    ("Over 1 Months & upto 2 Months", 31, 60),
    ("Over 2 Months & upto 6 Months", 61, 180),
    ("Over 6 Months & upto 12 Months", 181, 365),
    ("Over 1 Years & upto 3 Years", 366, 365*3),
    ("Over 3 Years & upto 5 Years", 365*3+1, 365*5),
    ("Over 5 Years & upto 7 Years", 365*5+1, 365*7),
    ("Over 7 Years & upto 10 Years", 365*7+1, 365*10),
    ("Over 10 Years & upto 12 Years", 365*10+1, 365*12),
    ("Over 12 Years & upto 15 Years", 365*12+1, 365*15),
    ("Over 15 Years & upto 18 Years", 365*15+1, 365*18),
    ("Over 18 Years & upto 20 Years", 365*18+1, 365*20),
    ("Over 20 Years & upto 30 Years", 365*20+1, 365*30),
    ("Over 30 Years & upto 50 Years", 365*30+1, 365*50),
]
ALM_BUCKET_NAMES = [b[0] for b in ALM_BUCKETS]

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def smart_pick_col(df: pd.DataFrame, candidates):
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        for c in cols:
            if cand.lower() == c:
                return cols[c]
    for cand in candidates:  # fuzzy contains
        for c in cols:
            if cand.lower() in c:
                return cols[c]
    return None

@st.cache_data(show_spinner=False)
def coerce_date(x):
    if pd.isna(x):
        return pd.NaT
    if isinstance(x, (datetime, date)):
        return pd.to_datetime(x)
    try:
        return pd.to_datetime(parser.parse(str(x), dayfirst=True, fuzzy=True))
    except Exception:
        return pd.NaT

@st.cache_data(show_spinner=False)
def normalise_types(val):
    if pd.isna(val):
        return np.nan
    s = str(val).strip().lower()
    if s in ("st", "short", "short-term", "short term"):
        return "ST"
    if s in ("lt", "long", "long-term", "long term"):
        return "LT"
    return val

def _to_number(s):
    s = str(s)
    s = s.replace(',', '').replace('%', '')
    for tok in ['INR', 'Rs', '₹']:
        s = s.replace(tok, '')
    s = s.strip()
    if s in ('', '-', '—'):
        return np.nan
    return pd.to_numeric(s, errors='coerce')

def tenor_to_alm_bucket_name(tenor_days):
    """Map effective tenor (days) to an ALM bucket."""
    if pd.isna(tenor_days):
        return "15 Days to 30 Days"  # neutral default
    d = int(tenor_days)
    for name, lo, hi in ALM_BUCKETS:
        if lo <= d <= hi:
            return name
    return ALM_BUCKETS[-1][0]  # clamp to longest bucket

# -----------------------------------------------------------------------------
# OCR (AWS Textract)
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=True, ttl=600)
def textract_tables_from_image(img_bytes: bytes, region: str = None):
    """Return a list of DataFrames extracted from TABLE blocks via Textract."""
    if region is None:
        region = st.secrets.get("AWS_DEFAULT_REGION", "ap-south-1")
    client = boto3.client(
        "textract",
        aws_access_key_id=st.secrets.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=st.secrets.get("AWS_SECRET_ACCESS_KEY"),
        region_name=region,
    )
    resp = client.analyze_document(Document={"Bytes": img_bytes}, FeatureTypes=["TABLES"])  # type: ignore
    blocks = resp.get("Blocks", [])

    blocks_map = {b["Id"]: b for b in blocks}
    table_blocks = [b for b in blocks if b.get("BlockType") == "TABLE"]

    def get_text(result, block_map, block):
        text = ""
        if "Relationships" in block:
            for r in block["Relationships"]:
                if r["Type"] == "CHILD":
                    for cid in r["Ids"]:
                        word = block_map[cid]
                        if word["BlockType"] == "WORD":
                            text += word.get("Text", "") + " "
                        if word["BlockType"] == "SELECTION_ELEMENT" and word.get("SelectionStatus") == "SELECTED":
                            text += "X "
        return text.strip()

    dataframes = []
    for table in table_blocks:
        rows = {}
        if "Relationships" not in table:
            continue
        for r in table["Relationships"]:
            if r["Type"] != "CHILD":
                continue
            for cid in r["Ids"]:
                cell = blocks_map[cid]
                if cell.get("BlockType") != "CELL":
                    continue
                row_idx = cell.get("RowIndex", 0)
                col_idx = cell.get("ColumnIndex", 0)
                text = get_text(resp, blocks_map, cell)
                rows.setdefault(row_idx, {})[col_idx] = text
        if not rows:
            continue
        max_cols = max(len(r) for r in rows.values())
        table_list = []
        for i in sorted(rows.keys()):
            row = rows[i]
            table_list.append([row.get(j, "") for j in range(1, max_cols + 1)])
        df = pd.DataFrame(table_list)
        if (df.iloc[0] != "").sum() >= max(1, df.shape[1] // 2):
            df.columns = [str(c).strip() if str(c).strip() else f"Col{idx+1}" for idx, c in enumerate(df.iloc[0])]
            df = df.drop(index=0).reset_index(drop=True)
        else:
            df.columns = [f"Col{idx+1}" for idx in range(df.shape[1])]
        dataframes.append(df)
    return dataframes

# -----------------------------------------------------------------------------
# Sidebar: inputs
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("📌 Draw Target (optional)")
    target_amount = st.number_input("Total amount you want to draw now", min_value=0.0, value=0.0, step=1.0)
    st.caption("If set, we'll show how many lines you need (in order) to meet this amount.")

    NEAR_WINDOW_DAYS = st.number_input("Near-availability window (days)", min_value=1, max_value=30, value=10)

    st.divider()
    st.header("ALM Mismatch by Bucket (₹)")
    st.caption("Positive = net cash outflow (needs funding). Negative = net cash inflow.")
    alm_mismatch_inputs = {}
    for bucket in ALM_BUCKET_NAMES:
        alm_mismatch_inputs[bucket] = st.number_input(bucket, value=0.0, step=1_00_000.0, format="%.2f")
    alm_weight = st.slider(
        "ALM priority weight",
        min_value=0.0, max_value=10.0, value=3.0, step=0.5,
        help="0 = ignore ALM. Higher = stronger priority for funding buckets with outflows."
    )

colA, colB = st.columns(2)
with colA:
    excel_file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"], key="excel")
with colB:
    image_file = st.file_uploader("Upload Image (PNG/JPG)", type=["png", "jpg", "jpeg"], key="image")

if not excel_file and not image_file:
    st.info("Upload an **Excel** or an **Image** to begin. Columns can be named flexibly — we'll auto-detect.")
    st.stop()

# -----------------------------------------------------------------------------
# Build DataFrame from input
# -----------------------------------------------------------------------------
raw = None
source = None

if excel_file is not None:
    try:
        xls = pd.ExcelFile(excel_file)
        if len(xls.sheet_names) > 1:
            sheet = st.selectbox("Select sheet", xls.sheet_names, index=0)
        else:
            sheet = xls.sheet_names[0]
        raw = pd.read_excel(xls, sheet_name=sheet)
        source = "excel"
    except Exception as e:
        st.error(f"Could not read Excel: {e}")
        st.stop()

if raw is None and image_file is not None:
    # Require secrets for Textract
    missing_keys = [k for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if k not in st.secrets]
    if missing_keys:
        st.error("Image OCR requires AWS Textract. Please set AWS credentials in Streamlit secrets: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, (optional) AWS_DEFAULT_REGION.")
        st.stop()
    try:
        image = Image.open(image_file).convert("RGB")
        st.image(image, caption="Uploaded image", use_column_width=True)
        img_bytes_io = BytesIO()
        image.save(img_bytes_io, format="PNG")
        img_bytes = img_bytes_io.getvalue()
    except Exception as e:
        st.error(f"Could not open image: {e}")
        st.stop()

    with st.spinner("Reading table from image via AWS Textract..."):
        tables = textract_tables_from_image(img_bytes)
    if not tables:
        st.error("No tables detected in the image. Try cropping to the table area or upload an Excel instead.")
        st.stop()
    if len(tables) > 1:
        idx = st.number_input("Multiple tables found — choose which to use", min_value=1, max_value=len(tables), value=1)
        raw = tables[idx-1]
    else:
        raw = tables[0]
    source = "image"

assert raw is not None

# -----------------------------------------------------------------------------
# Column mapping
# -----------------------------------------------------------------------------
map_cols = {}
map_cols['date']   = smart_pick_col(raw, DATE_COL_CANDIDATES)
map_cols['roi']    = smart_pick_col(raw, ROI_COL_CANDIDATES)
map_cols['amount'] = smart_pick_col(raw, AMOUNT_COL_CANDIDATES)
map_cols['tenor']  = smart_pick_col(raw, TENOR_COL_CANDIDATES)
map_cols['type']   = smart_pick_col(raw, TYPE_COL_CANDIDATES)

with st.expander("Detected column mapping"):
    st.json(map_cols)

missing = [k for k, v in map_cols.items() if v is None and k in ('date', 'roi', 'amount')]
if missing:
    st.error(f"Missing required columns (detected): {', '.join(missing)}. Please rename columns in your {source} or fix the image capture.")
    with st.expander("Preview of detected data"):
        st.write(raw.head())
    st.stop()

# -----------------------------------------------------------------------------
# Clean & derive
# -----------------------------------------------------------------------------
df = raw.copy()

try:
    df['__date'] = raw[map_cols['date']].apply(coerce_date)
except Exception:
    df['__date'] = pd.to_datetime(pd.Series([pd.NaT]*len(raw)))

df['__roi']    = raw[map_cols['roi']].apply(_to_number)
df['__amount'] = raw[map_cols['amount']].apply(_to_number)

if map_cols['type']:
    df['__type'] = raw[map_cols['type']].apply(normalise_types)
else:
    df['__type'] = np.nan

if map_cols['tenor']:
    df['__tenor_days'] = raw[map_cols['tenor']].apply(_to_number)
else:
    df['__tenor_days'] = np.nan

# Timezone-correct "today" (IST) and availability window
IST = pytz.timezone("Asia/Kolkata")
today = pd.Timestamp.now(IST).normalize()
df['__days_to_avail'] = (df['__date'] - today).dt.days

# Effective tenor: ST assumed 90 days if tenor missing
df['__effective_tenor_days'] = np.where(df['__type'].eq('ST') | df['__tenor_days'].isna(), 90, df['__tenor_days'])

# Near-window flag: 0=within window (best), 1=future but outside window, 2=past-dated
df['__near_flag'] = np.select(
    [
        (df['__days_to_avail'] >= 0) & (df['__days_to_avail'] <= NEAR_WINDOW_DAYS),
        (df['__days_to_avail'] < 0)
    ],
    [0, 2],
    default=1
)

# -------------------- ALM features --------------------
df['__alm_bucket']   = df['__effective_tenor_days'].apply(tenor_to_alm_bucket_name)
df['__alm_mismatch'] = df['__alm_bucket'].map(alm_mismatch_inputs).astype(float)

# Priority score from ALM:
#   Positive outflow (needs funding)  => higher priority => smaller score (better in ascending sort)
#   Negative inflow (surplus)         => lower priority  => larger score (worse)
df['__alm_priority'] = -alm_weight * df['__alm_mismatch']

# -----------------------------------------------------------------------------
# Sort priority: near-window → ALM pressure → ROI → days to availability → tenor
# -----------------------------------------------------------------------------
df_sorted = df.sort_values(
    by=['__near_flag', '__alm_priority', '__roi', '__days_to_avail', '__effective_tenor_days'],
    ascending=[True,         True,            True,   True,              True]
)

# -----------------------------------------------------------------------------
# Output views
# -----------------------------------------------------------------------------
display_cols = []
for label, key in [
    ("Date of availability", 'date'),
    ("ROI", 'roi'),
    ("Amount to be drawn", 'amount'),
    ("Tenor", 'tenor'),
    ("Type", 'type')
]:
    col = map_cols.get(key)
    if col:
        display_cols.append(col)

out = df_sorted.assign(
    **{
        'ALM Bucket': df_sorted['__alm_bucket'],
        'ALM Mismatch (₹)': df_sorted['__alm_mismatch'],
        'ALM Priority (↓ better)': df_sorted['__alm_priority'],
        'Availability (days from today)': df_sorted['__days_to_avail'],
        'Near-window? (0 best)': df_sorted['__near_flag'],
        'Effective Tenor (days)': df_sorted['__effective_tenor_days'],
        'Picked Amount': np.nan,
        'Remaining After Pick': np.nan,
    }
).reset_index(drop=True)

# Optional packing plan
if target_amount and target_amount > 0:
    remaining = target_amount
    for i, r in out.iterrows():
        amt = r['__amount'] if pd.notna(r['__amount']) else 0
        if amt <= 0 or remaining <= 0:
            continue
        take = min(amt, remaining)
        out.at[i, 'Picked Amount'] = take
        remaining -= take
        out.at[i, 'Remaining After Pick'] = max(0, remaining)

# -----------------------------------------------------------------------------
# Render
# -----------------------------------------------------------------------------
st.subheader("Recommended draw order")
st.dataframe(
    out[
        display_cols
        + [
            'ALM Bucket','ALM Mismatch (₹)','ALM Priority (↓ better)',
            'Availability (days from today)','Near-window? (0 best)','Effective Tenor (days)',
            'Picked Amount','Remaining After Pick'
        ]
    ]
)

st.caption(
    "Ranking = Near-window → ALM pressure (bucket outflow) → ROI → earlier availability → shorter tenor. "
    "Positive ALM mismatch = net cash **outflow** (fund sooner). Negative = **inflow** (can de-prioritize). "
    "ST tenor assumed 90 days if missing."
)
st.caption("Near-window flags: 0 = within window (best), 1 = future outside window, 2 = past-dated (deprioritized).")

# -----------------------------------------------------------------------------
# Downloads
# -----------------------------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    st.download_button(
        label="Download order (CSV)",
        data=out[display_cols + [
            'ALM Bucket','ALM Mismatch (₹)','ALM Priority (↓ better)',
            'Availability (days from today)','Near-window? (0 best)','Effective Tenor (days)'
        ]].to_csv(index=False).encode('utf-8'),
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
