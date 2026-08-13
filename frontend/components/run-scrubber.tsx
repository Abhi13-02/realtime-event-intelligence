"use client";

// A YouTube-style scrubber over discovery runs, shared by the topic timeline
// and the narrative deep-dive chart so the two cannot drift apart.
//
// Three things the previous inline implementation got wrong:
//
//   1. It fired onSelect on every change event while dragging, and each one
//      triggered a network fetch. Dragging across twenty runs meant twenty
//      requests, out-of-order responses, and a flickering loading state. Here
//      the handle moves freely and the fetch fires ONCE, on release.
//
//   2. Its range input was bound to the snapped value, so the thumb sprang back
//      to the nearest tick mid-drag and could never follow the pointer.
//
//   3. The input was fully transparent with no handle rendered, so there was
//      nothing to grab.
//
// Ticks are spaced evenly per run rather than proportionally to real time.
// Discovery fires on an interval but topics are only processed when due, so
// real spacing bunches runs into unclickable clusters after any quiet period.
// Even spacing keeps every run reachable; the labels carry the actual times.

import { useEffect, useState } from "react";

export default function RunScrubber({
  count,
  activeIdx,
  onSelect,
  labelFor,
  disabled = false,
}: {
  /** Number of runs, oldest first. */
  count: number;
  /** Currently committed run index. */
  activeIdx: number;
  /** Fires once, on release — never during the drag. */
  onSelect: (idx: number) => void;
  /** Tooltip text for a tick. */
  labelFor?: (idx: number) => string;
  disabled?: boolean;
}) {
  // While dragging, the handle follows this instead of activeIdx so the parent
  // is not re-fetching on every intermediate position.
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  // If the parent moves the selection (jump to latest, deep link), drop any
  // stale drag preview so the handle does not fight the new value.
  useEffect(() => {
    setDragIdx(null);
  }, [activeIdx]);

  if (count <= 1) return null;

  const shownIdx = dragIdx ?? activeIdx;
  const pct = (i: number) => (i / (count - 1)) * 100;

  const commit = () => {
    if (dragIdx !== null && dragIdx !== activeIdx) onSelect(dragIdx);
    setDragIdx(null);
  };

  return (
    <div
      style={{ position: "relative", height: 26, margin: "0 8px" }}
      // Release can land outside the input if the pointer drifts off it.
      onPointerUp={commit}
      onPointerLeave={() => dragIdx !== null && commit()}
    >
      {/* track */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: "50%",
          transform: "translateY(-50%)",
          height: 3,
          borderRadius: 99,
          background: "var(--border2)",
        }}
      />
      {/* elapsed portion */}
      <div
        style={{
          position: "absolute",
          left: 0,
          width: `${pct(shownIdx)}%`,
          top: "50%",
          transform: "translateY(-50%)",
          height: 3,
          borderRadius: 99,
          background: "var(--accent)",
          transition: dragIdx === null ? "width .18s" : "none",
        }}
      />
      {/* run ticks */}
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          title={labelFor?.(i)}
          onClick={() => !disabled && onSelect(i)}
          style={{
            position: "absolute",
            left: `${pct(i)}%`,
            top: "50%",
            width: 5,
            height: 5,
            marginLeft: -2.5,
            marginTop: -2.5,
            borderRadius: "50%",
            background: i <= shownIdx ? "var(--accent)" : "var(--textmute)",
            opacity: i === shownIdx ? 0 : 0.85,
            cursor: disabled ? "default" : "pointer",
          }}
        />
      ))}
      {/* the handle — visible, and what the pointer appears to drag */}
      <div
        style={{
          position: "absolute",
          left: `${pct(shownIdx)}%`,
          top: "50%",
          width: 13,
          height: 13,
          marginLeft: -6.5,
          marginTop: -6.5,
          borderRadius: "50%",
          background: "var(--accent)",
          boxShadow: "0 0 0 4px var(--accentsoft)",
          pointerEvents: "none",
          transition: dragIdx === null ? "left .18s" : "none",
        }}
      />
      {/* Real input on top: gives pointer dragging AND keyboard arrows/Home/End
          for free. step=1 over run indices means every position IS a run, so
          "snap to the nearest run" is inherent rather than computed. */}
      <input
        type="range"
        aria-label="Discovery run"
        min={0}
        max={count - 1}
        step={1}
        disabled={disabled}
        value={shownIdx}
        onChange={(e) => setDragIdx(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          margin: 0,
          opacity: 0,
          cursor: disabled ? "default" : "grab",
        }}
      />
    </div>
  );
}
