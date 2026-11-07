export const pct = (v: number | null | undefined): string =>
  v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(1)}%`;

/** Gap in percentage points, signed (computed minus published). */
export const gapPts = (v: number | null | undefined): string =>
  v === null || v === undefined ? "n/a" : `${v >= 0 ? "+" : "-"}${Math.abs(v * 100).toFixed(1)} pts`;

export const day = (iso: string | null | undefined): string => (iso ? iso.slice(0, 10) : "n/a");
