import { useEffect, useState } from "react";
import type { Result } from "./api";

/** Runs `fetcher` when `deps` change. A response only counts if its request is still the
 * current one; result and error are cleared when the selection changes. Pass `null` to skip. */
export function useResult<T>(fetcher: (() => Promise<Result<T>>) | null, deps: unknown[]) {
  const [result, setResult] = useState<Result<T> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setResult(null);
    setError(null);
    if (fetcher)
      fetcher()
        .then((r) => current && setResult(r))
        .catch((e: Error) => current && setError(e.message));
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { result, error };
}

/** Like useResult for the stage 3 routes, which return plain JSON rather than the envelope. */
export function useResultPlain<T>(fetcher: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setData(null);
    setError(null);
    fetcher()
      .then((r) => current && setData(r))
      .catch((e: Error) => current && setError(e.message));
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error };
}
