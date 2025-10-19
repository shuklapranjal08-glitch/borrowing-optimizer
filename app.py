# Deploy your Borrowing Optimiser to Streamlit Cloud (via GitHub)

This is a copy‑paste guide you can follow even if you’ve never used GitHub or Streamlit Cloud before. It includes ready‑to‑use code.

---

## 1) Create a GitHub repository (the place your app code lives)

1. Go to [https://github.com](https://github.com) → log in (create an account if needed).
2. Click **New** (top left) → **Repository name**: `borrowing-optimiser` → Keep **Public** → click **Create repository**.
3. On the new repo page, click **Add file → Create new file**.

We'll add the files below exactly as shown.

---

## 2) Add `requirements.txt` (packages your app needs)

Create a file called **requirements.txt** with this content:

```
streamlit>=1.37
pandas>=2.2
numpy>=1.26
python-dateutil>=2.9
openpyxl>=3.1
Pillow>=10.0
# Optional if you later enable OCR with AWS Textract
boto3>=1.34
```

> Note: If you don’t plan to use OCR now, you can remove `boto3`.

---

## 3) Add the app code: `app.py`

Create a file named **app.py** with this content:

```python
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date
from dateutil import parser

st.set_page_config(page_title="Borrowing Optimiser", page_icon="💸", layout="wide")
st.title("💸 Borrowing Optimiser")
st.write("Upload your Excel (and optionally paste mail text) to get the optimal draw order.")

# --- Helper functions -------------------------------------------------------
DATE_COL_CANDIDATES = ["Date of availability", "Availability Date", "Available On", "Availability"]
ROI_COL_CANDIDATES = ["ROI", "Interest", "Rate", "Rate of Interest"]
AMOUNT_COL_CANDIDATES = ["Amount to be drawn", "Amount", "Draw Amount", "Available Amount"]
TENOR_COL_CANDIDATES = ["Tenor", "Tenure", "Term"]
TYPE_COL_CANDIDATES = ["Type", "Loan Type"]  # values: ST / LT (or Short/Long)

NEAR_WINDOW_DAYS = st.number_input("Near-availability window (days)", min_value=1, max_value=30, value=10)

@st.cache_data(show_spinner=False)
def read_excel(file) -> pd.DataFrame:
    try:
        return pd.read_excel(file)
    except Exception as e:
        st.error(f"Could not read Excel: {e}")
        return pd.DataFrame()

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

# --- Sidebar: demand planning (optional) ------------------------------------
with st.sidebar:
    st.header("📌 Draw Target (optional)")
    target_amount = st.number_input("Total amount you want to draw now", min_value=0.0, value=0.0, step=1.0)
    st.caption("If set, we'll show how many lines you need (in order) to meet this amount.")

# --- Uploads ----------------------------------------------------------------
excel_file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])
mail_text = st.text_area("Paste mail body (optional)")

if excel_file is None:
    st.info("Upload an Excel to begin. Columns can be named flexibly — we'll auto-detect.")
    st.stop()

raw = read_excel(excel_file)
if raw.empty:
    st.stop()

# --- Column mapping ---------------------------------------------------------
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

# --- Clean & derive ---------------------------------------------------------
df = raw.copy()
df['__date'] = raw[map_cols['date']].apply(coerce_date)
df['__roi'] = pd.to_numeric(raw[map_cols['roi']], errors='coerce')
df['__amount'] = pd.to_numeric(raw[map_cols['amount']], errors='coerce')

# Loan type and tenor
if map_cols['type']:
    df['__type'] = raw[map_cols['type']].apply(normalise_types)
else:
    df['__type'] = np.nan

if map_cols['tenor']:
    df['__tenor_days'] = pd.to_numeric(raw[map_cols['tenor']], errors='coerce')
else:
    df['__tenor_days'] = np.nan

# Business rules
today = pd.to_datetime(date.today())
df['__days_to_avail'] = (df['__date'] - today).dt.days

# Short-term assumed 90 days if type is ST or tenor missing
df['__effective_tenor_days'] = np.where(df['__type'].eq('ST') | df['__tenor_days'].isna(), 90, df['__tenor_days'])

# Near-availability flag
# Priority 0 if 0 <= days <= window, else 1, else 2 if past (treat past as lowest priority or exclude)
df['__near_flag'] = np.select([
    (df['__days_to_avail'] >= 0) & (df['__days_to_avail'] <= NEAR_WINDOW_DAYS),
    (df['__days_to_avail'] < 0)
], [0, 2], default=1)

# Sort key: (near_flag ASC, ROI ASC, days_to_avail ASC, effective_tenor_days ASC)
# You can tweak weights if desired.
df_sorted = df.sort_values(by=['__near_flag','__roi','__days_to_avail','__effective_tenor_days'], ascending=[True, True, True, True])

# Prepare nice output
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

# Optional packing plan to meet a target amount
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

# Download buttons
@st.cache_data
def to_excel_bytes(df):
    from io import BytesIO
    with pd.ExcelWriter(BytesIO(), engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Borrowing_Order')
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
```

---

## 4) (Optional) Add `.streamlit/secrets.toml` for API keys

Only needed if you later integrate OCR (e.g., AWS Textract). In your repo, click **Add file → Create new file**, name it `.streamlit/secrets.toml` and put (example):

```
AWS_ACCESS_KEY_ID = "..."
AWS_SECRET_ACCESS_KEY = "..."
AWS_DEFAULT_REGION = "ap-south-1"
```

> Then in code you’d read via `st.secrets["AWS_ACCESS_KEY_ID"]` etc.

---

## 5) Commit each file to GitHub

At the bottom of the file editor, click **Commit changes**. Repeat for every file above until they all appear in your repo.

---

## 6) Deploy on Streamlit Cloud

1. Go to [https://share.streamlit.io](https://share.streamlit.io) (or [https://streamlit.io/cloud](https://streamlit.io/cloud)) and sign in with GitHub.
2. Click **New app**.
3. Choose the repo `borrowing-optimiser`, branch `main`, and **Main file path** = `app.py`.
4. Click **Deploy**. Your app will build and then open at a public URL you can share with your client.
5. If you added `secrets.toml` fields, set them in **App → Settings → Secrets** on Streamlit Cloud as well.

---

## 7) How to update the app later

* Edit files directly on GitHub (or push from your laptop). Each commit triggers a redeploy.
* Use **Manage app → Rerun** on Streamlit Cloud if you need a fresh run.

---

## 8) What Excel columns should I have?

At minimum (names are flexible — the app auto-detects):

* **Date of availability** (any date format; day‑first supported)
* **ROI** (numeric)
* **Amount to be drawn** (numeric)
  Optional:
* **Type** (ST/LT or Short/Long)
* **Tenor** (days) — if missing for ST, the app assumes **90 days**

---

## 9) Business rule tuning (if you want to change it)

The current sorting key is:

```
(near_flag ASC, ROI ASC, days_to_avail ASC, effective_tenor_days ASC)
```

* `near_flag` = 0 if available within the chosen window (default 10 days), 1 if later, 2 if already past.
* You can change weights or add new tie‑breakers (e.g., prefer larger available amount first) in the `sort_values` line.

---

## 10) Optional OCR to read mail images (when you need it)

For a fully serverless deploy, prefer **uploading Excel**. If you must parse images, enable an OCR API such as **AWS Textract** (recommended for reliability on Streamlit Cloud) and call it from `app.py` using `boto3`. This avoids native OS deps like Tesseract.

**Quick sketch (not enabled above):**

```python
import boto3, base64
textract = boto3.client('textract',
    aws_access_key_id=st.secrets['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=st.secrets['AWS_SECRET_ACCESS_KEY'],
    region_name=st.secrets.get('AWS_DEFAULT_REGION', 'ap-south-1')
)
# bytes = uploaded_image.getvalue()
# resp = textract.detect_document_text(Document={'Bytes': bytes})
# lines = [b['Text'] for b in resp['Blocks'] if b['BlockType']=='LINE']
# mail_text = "\n".join(lines)
```

---

## 11) Hand‑off checklist for your client

* ✅ Public Streamlit URL shared
* ✅ Sample Excel provided
* ✅ README in repo explaining columns/business rules
* ✅ (Optional) Secrets set if OCR or any API is used

---

## 12) Troubleshooting

* **Build fails with package error** → remove heavy/unused packages; ensure `requirements.txt` is small.
* **Dates not detected** → ensure the date column is present; check app’s detected columns under the error expander.
* **Wrong order** → tune the `NEAR_WINDOW_DAYS` in the UI; adjust sorting in code.
* **Large Excel** → consider pre‑filtering rows or using CSV.

---

### You’re done 🎉

Once deployed, share the Streamlit URL. Your client can upload the Excel and immediately see the recommended draw order + download CSVs.
