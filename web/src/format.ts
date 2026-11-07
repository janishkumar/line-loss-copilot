export const pct = (v: number | null | undefined): string =>
  v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(1)}%`;

/** Gap in percentage points, signed (computed minus published). */
export const gapPts = (v: number | null | undefined): string =>
  v === null || v === undefined ? "n/a" : `${v >= 0 ? "+" : "-"}${Math.abs(v * 100).toFixed(1)} pts`;

export const day = (iso: string | null | undefined): string => (iso ? iso.slice(0, 10) : "n/a");

export const hours = (s: number | null | undefined): string =>
  s === null || s === undefined ? "n/a" : `${(s / 3600).toFixed(1)} h`;

export const minutes = (s: number | null | undefined): string =>
  s === null || s === undefined ? "n/a" : `${(s / 60).toFixed(1)} min`;

export const num = (v: number | null | undefined, digits = 3): string =>
  v === null || v === undefined ? "n/a" : v.toFixed(digits);

/** Duration: minutes below one hour, hours from one hour up. */
export const duration = (s: number | null | undefined): string =>
  s === null || s === undefined ? "n/a" : s < 3600 ? minutes(s) : hours(s);
