import React, { useCallback, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDropzone } from "react-dropzone";
import * as XLSX from "xlsx";
import { Image as ImageIcon, FileSpreadsheet, Info, Plus, Minus } from "lucide-react";
import { motion } from "framer-motion";

// --- Helpers ---------------------------------------------------------------
const DATE_CANDIDATES = [
  "Date of availability",
  "Availability Date",
  "Available On",
  "Availability",
  "Date",
];
const ROI_CANDIDATES = ["ROI", "Interest", "Rate", "Rate of Interest"];
const AMOUNT_CANDIDATES = [
  "Amount to be drawn",
  "Amount",
  "Draw Amount",
  "Available Amount",
  "Amt",
];
const TENOR_CANDIDATES = ["Tenor", "Tenure", "Term", "Days"];
const TYPE_CANDIDATES = ["Type", "Loan Type"]; // ST/LT

// ALM buckets (in days)
const ALM_BUCKETS = [
  { label: "0 Days to 7 Days", min: 0, max: 7 },
  { label: "8 Days to 14 Days", min: 8, max: 14 },
  { label: "15 Days to 30 Days", min: 15, max: 30 },
  { label: "Over 1 Months & upto 2 Months", min: 31, max: 60 },
  { label: "Over 2 Months & upto 6 Months", min: 61, max: 180 },
  { label: "Over 6 Months & upto 12 Months", min: 181, max: 365 },
  { label: "Over 1 Years & upto 3 Years", min: 366, max: 365 * 3 },
  { label: "Over 3 Years & upto 5 Years", min: 365 * 3 + 1, max: 365 * 5 },
  { label: "Over 5 Years & upto 7 Years", min: 365 * 5 + 1, max: 365 * 7 },
  { label: "Over 7 Years & upto 10 Years", min: 365 * 7 + 1, max: 365 * 10 },
  { label: "Over 10 Years & upto 12 Years", min: 365 * 10 + 1, max: 365 * 12 },
  { label: "Over 12 Years & upto 15 Years", min: 365 * 12 + 1, max: 365 * 15 },
  { label: "Over 15 Years & upto 18 Years", min: 365 * 15 + 1, max: 365 * 18 },
  { label: "Over 18 Years & upto 20 Years", min: 365 * 18 + 1, max: 365 * 20 },
  { label: "Over 20 Years & upto 30 Years", min: 365 * 20 + 1, max: 365 * 30 },
  { label: "Over 30 Years & upto 50 Years", min: 365 * 30 + 1, max: 365 * 50 },
];

function pickCol(cols, candidates) {
  const lower = Object.fromEntries(cols.map((c) => [c.toLowerCase(), c]));
  for (const cand of candidates) {
    const exact = lower[cand.toLowerCase()];
    if (exact) return exact;
  }
  for (const cand of candidates) {
    for (const key in lower) {
      if (key.includes(cand.toLowerCase())) return lower[key];
    }
  }
  return null;
}

function coerceNumber(x) {
  if (x == null || x === "") return NaN;
  const s = String(x).replace(/[\,\s%]/g, "");
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

function coerceDate(x) {
  if (!x) return null;
  try {
    const d = new Date(x);
    if (isNaN(d.getTime())) return null;
    return d;
  } catch (e) {
    return null;
  }
}

function normaliseType(v) {
  if (!v && v !== 0) return null;
  const s = String(v).trim().toLowerCase();
  if (["st", "short", "short-term", "short term"].includes(s)) return "ST";
  if (["lt", "long", "long-term", "long term"].includes(s)) return "LT";
  return v;
}

function daysToBucket(days) {
  if (!Number.isFinite(days)) return null;
  for (const b of ALM_BUCKETS) {
    if (days >= b.min && days <= b.max) return b.label;
  }
  return null; // beyond 50 years
}

function sortRows(rows, nearWindowDays, almMap) {
  const today = new Date();
  return [...rows]
    .map((r) => {
      const d = coerceDate(r.__date);
      const daysToAvail = d
        ? Math.floor((d.getTime() - today.getTime()) / (24 * 3600 * 1000))
        : Number.POSITIVE_INFINITY;
      const tenor = Number.isFinite(r.__tenor_days)
        ? r.__tenor_days
        : r.__type === "ST"
        ? 90
        : 90;
      let nearFlag = 1;
      if (Number.isFinite(daysToAvail) && daysToAvail >= 0 && daysToAvail <= nearWindowDays) nearFlag = 0;
      if (Number.isFinite(daysToAvail) && daysToAvail < 0) nearFlag = 2;

      const almBucketLabel = daysToBucket(tenor);
      const almOutflow = Math.max(0, (almMap && almMap[almBucketLabel]) || 0); // positive = outflow → prioritise
      const almPriority = -almOutflow; // more outflow → more negative → sorted earlier

      return {
        ...r,
        __daysToAvail: daysToAvail,
        __nearFlag: nearFlag,
        __effTenor: tenor,
        __almPriority: almPriority,
        __almBucketLabel: almBucketLabel,
      };
    })
    .sort((a, b) => {
      // (near_flag ASC, ALM priority ASC, ROI ASC, days_to_avail ASC, effective_tenor_days ASC)
      return (
        a.__nearFlag - b.__nearFlag ||
        (a.__almPriority ?? 0) - (b.__almPriority ?? 0) ||
        (a.__roi ?? Infinity) - (b.__roi ?? Infinity) ||
        (a.__daysToAvail ?? Infinity) - (b.__daysToAvail ?? Infinity) ||
        (a.__effTenor ?? Infinity) - (b.__effTenor ?? Infinity)
      );
    });
}

// --- File parsing ----------------------------------------------------------
async function parseXlsx(file) {
  const data = await file.arrayBuffer();
  const wb = XLSX.read(data, { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]];
  const json = XLSX.utils.sheet_to_json(ws, { defval: "" });
  return json; // array of objects
}

// --- UI Components ---------------------------------------------------------

/* Runtime tests to validate sort logic (runs in browser console) */
if (typeof window !== "undefined") {
  (function runBorrowingOptimiserTests() {
    const day = 24 * 3600 * 1000;
    const today = new Date();
    const rows = [
      { __date: new Date(today.getTime() + 5 * day), __roi: 8, __tenor_days: 90, __type: "ST" },
      { __date: new Date(today.getTime() + 8 * day), __roi: 7, __tenor_days: 90, __type: "ST" },
      { __date: new Date(today.getTime() + 15 * day), __roi: 5, __tenor_days: 120, __type: "LT" },
      { __date: new Date(today.getTime() - 1 * day), __roi: 1, __tenor_days: 30, __type: "ST" },
    ];
    const sorted = sortRows(rows, 10, {});
    try {
      console.assert(sorted[0].__roi === 7, "Test 1: Near-window with lower ROI should rank first");
      console.assert(sorted[1].__roi === 8, "Test 2: Next near-window item should come next by ROI");
      console.assert(sorted[2].__roi === 5, "Test 3: Outside near-window comes after all near-window items");
      console.assert(sorted[3].__roi === 1 && sorted[3].__daysToAvail < 0, "Test 4: Past dates (nearFlag=2) come last");

      // Additional tie-break test: same ROI & near flag → earlier availability wins
      const rows2 = [
        { __date: new Date(today.getTime() + 2 * day), __roi: 6, __tenor_days: 90, __type: "ST" },
        { __date: new Date(today.getTime() + 1 * day), __roi: 6, __tenor_days: 120, __type: "LT" },
      ];
      const tSorted = sortRows(rows2, 10, {});
      console.assert(
        tSorted[0].__daysToAvail <= tSorted[1].__daysToAvail,
        "Test 5: Earlier date should precede when ROI and near flag are equal"
      );

      // New ALM test: large outflow in 7–10y bucket prioritises matching tenor
      const almRows = [
        { __date: new Date(today.getTime() + 5 * day), __roi: 6, __tenor_days: 365 * 8, __type: "LT" }, // 8y
        { __date: new Date(today.getTime() + 5 * day), __roi: 5, __tenor_days: 90, __type: "ST" },       // 90d
      ];
      const almMap = { "Over 7 Years & upto 10 Years": 1000 };
      const aSorted = sortRows(almRows, 10, almMap);
      console.assert(aSorted[0].__tenor_days >= 365 * 7, "Test 6: ALM outflow prioritises matching long-tenor line");

      console.debug("Borrowing Optimiser tests passed ✅");
    } catch (e) {
      console.error("Borrowing Optimiser tests failed ❌", e);
    }
  })();
}

function DropCard({ icon: Icon, title, subtitle, accept, onFiles }) {
  const onDrop = useCallback(
    (accepted) => {
      if (accepted?.length) onFiles(accepted);
    },
    [onFiles]
  );
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, accept });
  return (
    <Card className="border-dashed border-2">
      <CardContent className="p-6">
        <div
          {...getRootProps()}
          className={`flex items-center justify-between gap-4 rounded-xl p-6 border-2 border-dashed cursor-pointer ${
            isDragActive ? "border-muted-foreground/60" : "border-muted"
          }`}
        >
          <div className="flex items-center gap-4">
            <div className="rounded-2xl p-3 bg-muted/50">
              <Icon className="w-6 h-6" />
            </div>
            <div>
              <div className="font-medium">{title}</div>
              <div className="text-sm text-muted-foreground">{subtitle}</div>
            </div>
          </div>
          <Button variant="secondary">Browse files</Button>
          <input {...getInputProps()} />
        </div>
      </CardContent>
    </Card>
  );
}

function NumberWithSteppers({ label, value, setValue, min = 0, max = 999 }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="icon" onClick={() => setValue((v) => Math.max(min, Number(v) - 1))}>
          <Minus className="w-4 h-4" />
        </Button>
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value.replace(/[^0-9.]/g, ""))}
          className="text-center"
          inputMode="numeric"
        />
        <Button type="button" variant="outline" size="icon" onClick={() => setValue((v) => Math.min(max, Number(v) + 1))}>
          <Plus className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}

// --- Main App --------------------------------------------------------------
export default function BorrowingOptimiserUI() {
  const [targetAmount, setTargetAmount] = useState("0.00");
  const [nearDays, setNearDays] = useState("10");

  const [sheetRows, setSheetRows] = useState([]); // parsed rows from Excel
  const [colMap, setColMap] = useState({});
  const [imagePreview, setImagePreview] = useState(null);

  // ALM state (positive = net cash outflow, negative = net inflow)
  const [almMap, setAlmMap] = useState(() => Object.fromEntries(ALM_BUCKETS.map((b) => [b.label, 0])));

  const onExcel = async (files) => {
    const f = files[0];
    if (!f) return;
    const json = await parseXlsx(f);
    setSheetRows(json);

    // infer columns once
    const cols = json.length ? Object.keys(json[0]) : [];
    const dateCol = pickCol(cols, DATE_CANDIDATES);
    const roiCol = pickCol(cols, ROI_CANDIDATES);
    const amountCol = pickCol(cols, AMOUNT_CANDIDATES);
    const tenorCol = pickCol(cols, TENOR_CANDIDATES);
    const typeCol = pickCol(cols, TYPE_CANDIDATES);

    setColMap({ dateCol, roiCol, amountCol, tenorCol, typeCol });
  };

  const onImage = (files) => {
    const f = files[0];
    if (!f) return;
    const url = URL.createObjectURL(f);
    setImagePreview(url);
  };

  const processed = useMemo(() => {
    if (!sheetRows.length) return [];
    const { dateCol, roiCol, amountCol, tenorCol, typeCol } = colMap;
    const rows = sheetRows.map((r) => ({
      __date: r[dateCol],
      __roi: coerceNumber(r[roiCol]),
      __amount: coerceNumber(r[amountCol]),
      __tenor_days: coerceNumber(r[tenorCol]),
      __type: normaliseType(r[typeCol]),
      _display: r,
    }));
    return sortRows(rows, Number(nearDays || 10), almMap);
  }, [sheetRows, colMap, nearDays, almMap]);

  return (
    <div className="min-h-screen bg-background">
      <div className="grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-6 p-6">
        {/* Sidebar */}
        <aside>
          <Card className="sticky top-6">
            <CardHeader>
              <CardTitle className="flex items-start gap-2">
                <span className="text-2xl">📌</span>
                <span>
                  Draw Target
                  <div className="text-sm text-muted-foreground font-normal">(optional)</div>
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div>
                <Label>Total amount you want to draw now</Label>
                <div className="flex items-center gap-2 mt-2">
                  <Button variant="outline" size="icon" onClick={() => setTargetAmount((v) => (Math.max(0, Number(v) - 1)).toFixed(2))}>
                    <Minus className="w-4 h-4" />
                  </Button>
                  <Input value={targetAmount} onChange={(e) => setTargetAmount(e.target.value.replace(/[^0-9.]/g, ""))} />
                  <Button variant="outline" size="icon" onClick={() => setTargetAmount((v) => (Number(v) + 1).toFixed(2))}>
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
                <p className="text-sm text-muted-foreground mt-1">If set, we'll show how many lines you need (in order) to meet this amount.</p>
              </div>

              <div>
                <Label>Near-availability window (days)</Label>
                <div className="flex items-center gap-2 mt-2">
                  <Button type="button" variant="outline" size="icon" onClick={() => setNearDays((v) => String(Math.max(1, Number(v) - 1)))}>
                    <Minus className="w-4 h-4" />
                  </Button>
                  <Input value={nearDays} onChange={(e) => setNearDays(e.target.value.replace(/[^0-9]/g, ""))} className="text-center" inputMode="numeric" />
                  <Button type="button" variant="outline" size="icon" onClick={() => setNearDays((v) => String(Math.min(30, Number(v) + 1)))}>
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
              </div>

              <div>
                <Label>ALM Mismatch (₹ / chosen unit) — positive = net cash outflow, negative = inflow</Label>
                <div className="mt-3 max-h-[360px] overflow-auto pr-1 space-y-2">
                  {ALM_BUCKETS.map((b) => (
                    <div key={b.label} className="grid grid-cols-[1fr_110px] gap-2 items-center">
                      <span className="text-xs">{b.label}</span>
                      <Input
                        value={almMap[b.label]}
                        onChange={(e) => setAlmMap((m) => ({ ...m, [b.label]: Number(e.target.value || 0) }))}
                        placeholder="0"
                        inputMode="numeric"
                      />
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground mt-1">Lines whose **tenor** falls in a bucket with higher **positive** mismatch are prioritised.</p>
              </div>
            </CardContent>
          </Card>
        </aside>

        {/* Main */}
        <main className="space-y-6">
          <motion.h1 initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="text-4xl md:text-6xl font-extrabold tracking-tight">
            💸 Borrowing Optimiser — Excel or Image Upload
          </motion.h1>
          <p className="text-muted-foreground text-lg max-w-3xl">
            Upload an <span className="font-semibold">Excel</span> <em>or</em> an image of the mail/table. If image is uploaded, we'll eventually OCR it.
          </p>

          <div className="grid md:grid-cols-2 gap-6">
            <DropCard
              icon={FileSpreadsheet}
              title="Upload Excel (.xlsx)"
              subtitle="Drag and drop file here"
              accept={{ "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"] }}
              onFiles={onExcel}
            />
            <DropCard
              icon={ImageIcon}
              title="Upload Image (PNG/JPG)"
              subtitle="Drag and drop file here"
              accept={{ "image/*": [".png", ".jpg", ".jpeg"] }}
              onFiles={onImage}
            />
          </div>

          <Card className="bg-muted/30">
            <CardContent className="p-4 flex items-start gap-3">
              <Info className="mt-0.5 w-4 h-4" />
              <div className="text-sm text-muted-foreground">
                Upload an <strong>Excel</strong> or an <strong>Image</strong> to begin. Columns can be named flexibly — we'll auto‑detect.
              </div>
            </CardContent>
          </Card>

          {/* Image preview (no OCR wired in this frontend) */}
          {imagePreview && (
            <Card>
              <CardHeader>
                <CardTitle>Image preview</CardTitle>
              </CardHeader>
              <CardContent>
                <img src={imagePreview} alt="uploaded" className="rounded-xl max-h-96 object-contain" />
                <p className="text-sm text-muted-foreground mt-2">OCR not wired in this pure-frontend demo. We can connect an OCR API if you want end‑to‑end image → table.</p>
              </CardContent>
            </Card>
          )}

          {/* Results */}
          {!!processed.length && (
            <Card>
              <CardHeader>
                <CardTitle>Recommended draw order</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-auto rounded-xl border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="text-left p-2">Date of availability</th>
                        <th className="text-left p-2">ROI</th>
                        <th className="text-left p-2">Amount to be drawn</th>
                        <th className="text-left p-2">Tenor</th>
                        <th className="text-left p-2">Type</th>
                        <th className="text-left p-2">Availability (days from today)</th>
                        <th className="text-left p-2">Near-window? (0 best)</th>
                        <th className="text-left p-2">Effective Tenor (days)</th>
                        <th className="text-left p-2">ALM Bucket</th>
                      </tr>
                    </thead>
                    <tbody>
                      {processed.map((r, i) => (
                        <tr key={i} className="odd:bg-background">
                          <td className="p-2">{r.__date ? String(r.__date) : ""}</td>
                          <td className="p-2">{Number.isFinite(r.__roi) ? r.__roi : ""}</td>
                          <td className="p-2">{Number.isFinite(r.__amount) ? r.__amount : ""}</td>
                          <td className="p-2">{Number.isFinite(r.__tenor_days) ? r.__tenor_days : ""}</td>
                          <td className="p-2">{r.__type ?? ""}</td>
                          <td className="p-2">{Number.isFinite(r.__daysToAvail) ? r.__daysToAvail : ""}</td>
                          <td className="p-2">{r.__nearFlag}</td>
                          <td className="p-2">{Number.isFinite(r.__effTenor) ? r.__effTenor : ""}</td>
                          <td className="p-2">{r.__almBucketLabel || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </main>
      </div>
    </div>
  );
}
