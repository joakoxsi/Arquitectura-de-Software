import { useEffect, useRef } from "react";

/** Ejecuta `fn` de inmediato y luego cada `ms` milisegundos mientras `active`. */
export function usePolling(fn: () => void | Promise<void>, ms: number, deps: unknown[], active = true) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!active) return;
    saved.current();
    const id = setInterval(() => saved.current(), ms);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, active, ...deps]);
}
