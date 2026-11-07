import { useEffect, useState } from "react";
import { getAssets, type LineInfo } from "../api";

export interface Selection {
  lineId: string;
  start: string;
  end: string;
}

/** Line or machine plus an optional date window; empty dates mean the tool default. */
export default function AssetPicker({
  value, onChange, system, allLabel, showWindow = true,
}: {
  value: Selection;
  onChange: (s: Selection) => void;
  system?: "brick" | "piade";
  allLabel?: string;
  showWindow?: boolean;
}) {
  const [lines, setLines] = useState<LineInfo[]>([]);
  useEffect(() => {
    getAssets().then((r) => setLines(r.data?.lines ?? [])).catch(() => setLines([]));
  }, []);
  const shown = lines.filter((l) => !system || l.source_system === system);
  return (
    <div className="controls">
      <label>
        Line or machine
        <select value={value.lineId} onChange={(e) => onChange({ ...value, lineId: e.target.value })}>
          {allLabel && <option value="">{allLabel}</option>}
          {shown.map((l) => (
            <option key={l.line_id} value={l.line_id}>
              {l.line_id === "brick" ? "brick (heavy clay brick line)" : `${l.line_id} (PIADE machine)`}
            </option>
          ))}
        </select>
      </label>
      {showWindow && (<>
      <label>
        From
        <input type="date" value={value.start} onChange={(e) => onChange({ ...value, start: e.target.value })} />
      </label>
      <label>
        To (exclusive)
        <input type="date" value={value.end} onChange={(e) => onChange({ ...value, end: e.target.value })} />
      </label>
      </>)}
    </div>
  );
}

export const scopeOf = (s: Selection) => ({
  line_id: s.lineId || undefined,
  start: s.start || undefined,
  end: s.end || undefined,
});
