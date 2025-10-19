import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date
from dateutil import parser
from io import BytesIO
from PIL import Image

# Optional (only used when an image is uploaded)
import boto3

st.set_page_config(page_title="Borrowing Optimiser", page_icon="💸", layout="wide")
st.title("💸 Borrowing Optimiser — Excel or Image Upload")
st.write("Upload an Excel **or** an image of the mail/table. If image is uploaded, we'll use AWS Textract to read it.")

# ---------------------------- Config ---------------------------------------
DATE_COL_CANDIDATES = ["Date of availability", "Availability Date", "Available On", "Availability", "Date"]
ROI_COL_CANDIDATES = ["ROI", "Interest", "Rate", "Rate of Interest"]
AMOUNT_COL_CANDIDATES = ["Amount to be drawn", "Amount", "Draw Amount", "Available Amount", "Amt"]
TENOR_COL_CANDIDATES = ["Tenor", "Tenure", "Term", "Days"]
TYPE_COL_CANDIDATES = ["Type", "Loan Type"]

NEAR_WINDOW_DAYS = st.number_input("Near-availability window (days)", min_value=1, max_value=30, value=10)

# ---------------------------- Helpers --------------------------------------
@st.cache_data(show_spinner=False)
def smart_pick_col(df: pd.DataFrame, candidates):
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        for c in cols:
            if cand.lower() == c:
                return cols[c]
    # fuzzy contains match
    for cand in candidates:
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

# ---------------------------- OCR (AWS Textract) ---------------------------
@st.cache_data(show_spinner=True)
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

    # Build maps
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
        # Normalize to rectangular
        max_cols = max(len(r) for r in rows.values())
        table_list = []
        for i in sorted(rows.keys()):
            row = rows[i]
            table_list.append([row.get(j, "") for j in range(1, max_cols + 1)])
        df = pd.DataFrame(table_list)
        # Heuristic: first row as header if it has non-empty majority
        if (df.iloc[0] != "").sum() >= max(1, df.shape[1] // 2):
            df.columns = [str(c).strip() if str(c).strip() else f"Col{idx+1}" for idx, c in enumerate(df.iloc[0])]
            df = df.drop(index=0).reset_index(drop=True)
        else:
            df.columns = [f"Col{idx+1}" for idx in range(df.shape[1])]
        dataframes.append(df)
    return dataframes

# ---------------------------- UI: Inputs -----------------------------------
with st.sidebar:
    st.header("📌 Draw Target (optional)")
    target_amount = st.number_input("Total amount you want to draw now", min_value=0.0, value=0.0, step=1.0)
    st.caption("If set, we'll show how many lines you need (in order) to meet this amount.")

colA, colB = st.columns(2)
with colA:
    excel_file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"], key="excel")
with colB:
    image_file = st.file_uploader("Upload Image (PNG/JPG)", type=["png", "jpg", "jpeg"], key="image")

if not excel_file and not image_file:
    st.info("Upload an **Excel** or an **Image** to begin. Columns can be named flexibly — we'll auto-detect.")
    st.stop()

# ---------------------------- Build DataFrame ------------------------------
raw = None
source = None

if excel_file is not None:
    try:
        raw = pd.read_excel(excel_file)
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
    # Load and preview image
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
    # If multiple tables, let user pick one
    if len(tables) > 1:
        idx = st.number_input("Multiple tables found — choose which to use", min_value=1, max_value=len(tables), value=1)
        raw = tables[idx-1]
    else:
        raw = tables[0]
    source = "image"

assert raw is not None

# ---------------------------- Column mapping -------------------------------
map_cols = {}
map_cols['date'] = smart_pick_col(raw, DATE_COL_CANDIDATES)
map_cols['roi'] = smart_pick_col(raw, ROI_COL_CANDIDATES)
map_cols['amount'] = smart_pick_col(raw, AMOUNT_COL_CANDIDATES)
map_cols['tenor'] = smart_pick_col(raw, TENOR_COL_CANDIDATES)
map_cols['type'] = smart_pick_col(raw, TYPE_COL_CANDIDATES)

missing = [k for k,v in map_cols.items() if v is None and k in ('date','roi','amount')]
if missing:
    st.error(f"Missing required columns (detected): {', '.join(missing)}. Please rename columns in your {source} or fix the image capture.")
    with st.expander("Preview of detected data"):
        st.write(raw.head())
    st.stop()

# ---------------------------- Clean & derive -------------------------------
df = raw.copy()

try:
    df['__date'] = raw[map_cols['date']].apply(coerce_date)
except Exception:
    df['__date'] = pd.to_datetime(pd.NaT)

df['__roi'] = pd.to_numeric(raw[map_cols['roi']].astype(str).str.replace('%','', regex=False), errors='coerce')
df['__amount'] = pd.to_numeric(raw[map_cols['amount']].astype(str).str.replace(',','', regex=False), errors='coerce')

if map_cols['type']:
    df['__type'] = raw[map_cols['type']].apply(normalise_types)
else:
    df['__type'] = np.nan

if map_cols['tenor']:
    df['__tenor_days'] = pd.to_numeric(raw[map_cols['tenor']], errors='coerce')
else:
    df['__tenor_days'] = np.nan

# Rules
today = pd.to_datetime(date.today())
df['__days_to_avail'] = (df['__date'] - today).dt.days

df['__effective_tenor_days'] = np.where(df['__type'].eq('ST') | df['__tenor_days'].isna(), 90, df['__tenor_days'])

df['__near_flag'] = np.select([
    (df['__days_to_avail'] >= 0) & (df['__days_to_avail'] <= NEAR_WINDOW_DAYS),
    (df['__days_to_avail'] < 0)
], [0, 2], default=1)

# Sort priority
df_sorted = df.sort_values(by=['__near_flag','__roi','__days_to_avail','__effective_tenor_days'], ascending=[True, True, True, True])

# Output view columns
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

# Optional packing plan
plan = None
if target_amount and target_amount > 0:
    remaining = target_amount
    picks = []
    for _, r in out.iterrows():
        amt = r['__amount'] if not np.isnan(r['__amount']) else 0
        if amt <= 0:
            continue
        take = min(amt, remaining)
        picks.append({'Picked Amount': take, 'Remaining After Pick': max(0, remaining - take)})
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

# Downloads
col1, col2 = st.columns(2)
with col1:
    st.download_button(
        label="Download order (CSV)",
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

st.caption("Rules: minimize ROI; prefer lines available within the near window; break ties by earlier date and shorter tenor. ST assumed 90 days when tenor missing. For OCR, this app uses AWS Textract via Streamlit secrets.")
