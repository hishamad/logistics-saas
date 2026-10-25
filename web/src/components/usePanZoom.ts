// Pan and zoom for an SVG map by moving its viewBox: drag to pan, double-click, buttons,
// pinch (two fingers, or a trackpad pinch, which arrives as ctrl + wheel) to zoom.
// A plain mouse wheel keeps scrolling the page, so the map never traps it.
import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";

type View = { x: number; y: number; w: number; h: number };
const MAX_ZOOM = 8;

export function usePanZoom(width: number, height: number) {
  const full: View = { x: 0, y: 0, w: width, h: height };
  const [view, setView] = useState<View>(full);
  const svg = useRef<SVGSVGElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const moved = useRef(false);

  const fit = useCallback(
    (v: View): View => {
      const w = Math.min(width, Math.max(width / MAX_ZOOM, v.w));
      const h = (w * height) / width;
      return { w, h, x: Math.min(width - w, Math.max(0, v.x)), y: Math.min(height - h, Math.max(0, v.y)) };
    },
    [width, height],
  );

  /** A screen point in map units. */
  const at = useCallback((clientX: number, clientY: number, v: View) => {
    const rect = svg.current!.getBoundingClientRect();
    return { x: v.x + ((clientX - rect.left) / rect.width) * v.w, y: v.y + ((clientY - rect.top) / rect.height) * v.h };
  }, []);

  const zoomAt = useCallback(
    (factor: number, clientX?: number, clientY?: number) =>
      setView((v) => {
        const p = clientX === undefined || !svg.current ? { x: v.x + v.w / 2, y: v.y + v.h / 2 } : at(clientX, clientY!, v);
        return fit({ x: p.x - (p.x - v.x) / factor, y: p.y - (p.y - v.y) / factor, w: v.w / factor, h: v.h / factor });
      }),
    [at, fit],
  );

  useEffect(() => {
    const element = svg.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      zoomAt(Math.exp(-event.deltaY * 0.01), event.clientX, event.clientY);
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [zoomAt]);

  const handlers = {
    onPointerDown(event: PointerEvent<SVGSVGElement>) {
      pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
      moved.current = false;
      event.currentTarget.setPointerCapture?.(event.pointerId);
    },
    onPointerMove(event: PointerEvent<SVGSVGElement>) {
      const last = pointers.current.get(event.pointerId);
      if (!last || !svg.current) return;
      const others = [...pointers.current.entries()].filter(([id]) => id !== event.pointerId);
      if (others.length === 1) {
        // Pinch: zoom by how much the two fingers spread, around their middle.
        const [, other] = others[0];
        const before = Math.hypot(last.x - other.x, last.y - other.y);
        const after = Math.hypot(event.clientX - other.x, event.clientY - other.y);
        if (before > 0) zoomAt(after / before, (event.clientX + other.x) / 2, (event.clientY + other.y) / 2);
      } else {
        const rect = svg.current.getBoundingClientRect();
        const [dx, dy] = [event.clientX - last.x, event.clientY - last.y];
        if (Math.abs(dx) + Math.abs(dy) > 2) moved.current = true;
        setView((v) => fit({ ...v, x: v.x - (dx / rect.width) * v.w, y: v.y - (dy / rect.height) * v.h }));
      }
      pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    },
    onPointerUp(event: PointerEvent<SVGSVGElement>) {
      pointers.current.delete(event.pointerId);
    },
    onPointerCancel(event: PointerEvent<SVGSVGElement>) {
      pointers.current.delete(event.pointerId);
    },
    onDoubleClick(event: { clientX: number; clientY: number }) {
      zoomAt(2, event.clientX, event.clientY);
    },
  };

  return {
    svg,
    view,
    handlers,
    zoomed: view.w < width - 0.5,
    zoomIn: () => zoomAt(1.6),
    zoomOut: () => zoomAt(1 / 1.6),
    reset: () => setView(full),
    /** Map units per CSS pixel at full view, so marks keep their size when zoomed. */
    scale: view.w / width,
  };
}
