import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "./api";

// Schedule after completion: no overlapping requests, no polling hidden tabs,
// and no response from an old page can overwrite the next page's state.
export function useResource(path, interval = 30000) {
  const [state, setState] = useState({
    data: null,
    error: null,
    loading: true,
    updatedAt: null,
  });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    if (!path) {
      setState({ data: null, error: null, loading: false, updatedAt: null });
      return;
    }
    let active = true,
      initial = true,
      timer;
    const controller = new AbortController();
    setState((old) => ({ ...old, loading: true }));
    async function load() {
      if (!active) return;
      // A page opened in a background tab still needs its initial data,
      // especially resources with polling disabled (interval === 0).
      if (initial || !document.hidden) {
        initial = false;
        try {
          const data = await api(path, { signal: controller.signal });
          if (active)
            setState({
              data,
              error: null,
              loading: false,
              updatedAt: new Date(),
            });
        } catch (error) {
          if (active) setState((old) => ({ ...old, error, loading: false }));
          if (error.status === 401) return;
        }
      }
      if (active && interval) timer = setTimeout(load, interval);
    }
    load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, interval, revision]);
  return { ...state, refresh };
}

export function useUnsavedChanges(dirty) {
  useEffect(() => {
    if (!dirty) return;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

export function useAction() {
  const pending = useRef(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  async function run(fn, done) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const result = await fn();
      setNotice({
        severity: result?.warnings?.length ? "warning" : "success",
        text: [result?.message || "Done", ...(result?.warnings || [])].join(
          " · ",
        ),
      });
      done?.(result);
      return result;
    } catch (error) {
      setNotice({
        severity: "error",
        text: error.message,
        status: error.status,
      });
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return { busy, notice, setNotice, run };
}
