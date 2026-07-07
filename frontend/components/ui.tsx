"use client";

// Small design-system primitives — all styling driven by the token layer.

import { type ReactNode, type ButtonHTMLAttributes, useEffect } from "react";
import { statusColors } from "@/lib/format";

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";

const btnBase =
  "inline-flex items-center justify-center gap-1.5 font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

const btnStyles: Record<BtnVariant, string> = {
  primary:
    "bg-accent text-accentfg hover:bg-accent2 border border-transparent font-semibold",
  secondary: "bg-bg2 text-dim border border-line2 hover:text-ink",
  ghost: "bg-transparent text-dim border border-transparent hover:bg-bg2 hover:text-ink",
  danger: "bg-transparent text-neg border border-transparent hover:bg-negsoft",
};

export function Btn({
  variant = "secondary",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: BtnVariant;
}) {
  return (
    <button
      {...rest}
      className={`${btnBase} ${btnStyles[variant]} ${className}`}
      style={{
        height: 30,
        padding: "0 12px",
        borderRadius: "var(--radius)",
        fontSize: 12.5,
        ...rest.style,
      }}
    >
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
  style,
  onClick,
}: {
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={`bg-panel border border-line ${onClick ? "cursor-pointer hover:border-line2 transition-colors" : ""} ${className}`}
      style={{ borderRadius: "var(--radius)", ...style }}
    >
      {children}
    </div>
  );
}

/** Status chip: dot + label, colored per handoff status mapping */
export function StatusChip({ status, label }: { status: string; label?: string }) {
  const { fg, bg } = statusColors(status);
  return (
    <span
      className="inline-flex items-center gap-[5px] font-semibold"
      style={{
        fontSize: 10,
        color: fg,
        background: bg,
        padding: "3px 9px",
        borderRadius: 99,
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: fg }} />
      {label ?? status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

export function NewBadge() {
  return (
    <span
      className="font-bold text-accentfg bg-accent"
      style={{ fontSize: 9, letterSpacing: ".05em", padding: "2px 6px", borderRadius: 4 }}
    >
      NEW
    </span>
  );
}

export function RevivalBadge() {
  return (
    <span
      className="font-bold text-warn bg-warnsoft"
      style={{
        fontSize: 9,
        letterSpacing: ".05em",
        padding: "1px 5px",
        borderRadius: 4,
        border: "1px solid var(--warn)",
      }}
    >
      REVIVAL
    </span>
  );
}

export function Input({
  className = "",
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...rest}
      className={`w-full bg-bg2 text-ink border border-line2 outline-none focus:border-accent transition-colors placeholder:text-mute ${className}`}
      style={{
        padding: "9px 11px",
        borderRadius: "var(--radius)",
        fontSize: 13,
        ...rest.style,
      }}
    />
  );
}

export function Textarea({
  className = "",
  ...rest
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...rest}
      className={`w-full bg-bg2 text-ink border border-line2 outline-none focus:border-accent transition-colors placeholder:text-mute ${className}`}
      style={{
        padding: "9px 11px",
        borderRadius: "var(--radius)",
        fontSize: 13,
        minHeight: 70,
        resize: "vertical",
        lineHeight: 1.5,
        ...rest.style,
      }}
    />
  );
}

export function Label({ children }: { children: ReactNode }) {
  return (
    <label className="block text-dim" style={{ fontSize: 11, fontWeight: 550, marginBottom: 6 }}>
      {children}
    </label>
  );
}

/** iOS-style toggle per handoff settings spec */
export function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className="relative transition-colors"
      style={{
        width: 36,
        height: 20,
        borderRadius: 99,
        border: "none",
        background: on ? "var(--accent)" : "var(--border2)",
      }}
    >
      <span
        className="absolute transition-all"
        style={{
          top: 2,
          left: on ? 18 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "#fff",
          boxShadow: "0 1px 2px rgba(0,0,0,.3)",
        }}
      />
    </button>
  );
}

/** Bottom-pinned pager: "Page x / y" + Prev/Next */
export function Pager({
  page,
  totalPages,
  onPrev,
  onNext,
  compact = false,
}: {
  page: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
  compact?: boolean;
}) {
  return (
    <div
      className="flex items-center justify-between border-t border-line"
      style={{ marginTop: 12, paddingTop: 12, flex: "none" }}
    >
      <span className="text-mute" style={{ fontSize: 11 }}>
        Page {page} / {Math.max(totalPages, 1)}
      </span>
      <div className="flex" style={{ gap: 6 }}>
        <Btn
          onClick={onPrev}
          disabled={page <= 1}
          style={{ height: compact ? 26 : 28, padding: "0 10px", fontSize: 11.5, borderRadius: "var(--radiussm)" }}
        >
          Prev
        </Btn>
        <Btn
          onClick={onNext}
          disabled={page >= totalPages}
          style={{ height: compact ? 26 : 28, padding: "0 10px", fontSize: 11.5, borderRadius: "var(--radiussm)" }}
        >
          Next
        </Btn>
      </div>
    </div>
  );
}

export function Modal({
  open,
  onClose,
  children,
  maxWidth = 480,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  maxWidth?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      onClick={onClose}
      className="fixed inset-0 grid place-items-center nifade"
      style={{ zIndex: 100, background: "rgba(0,0,0,.5)", backdropFilter: "blur(3px)", padding: 28 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full bg-panel border border-line2 overflow-hidden"
        style={{
          maxWidth,
          maxHeight: "88vh",
          overflowY: "auto",
          borderRadius: "var(--radiuslg)",
          boxShadow: "var(--shadowlg)",
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className="flex flex-col" style={{ gap: "var(--gap)" }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="flex bg-panel border border-line"
          style={{ gap: 14, padding: 14, borderRadius: "var(--radius)" }}
        >
          <div className="shimmer" style={{ width: 62, height: 62, flex: "none", borderRadius: "var(--radiussm)" }} />
          <div className="flex-1 flex flex-col" style={{ gap: 9, paddingTop: 3 }}>
            <div className="shimmer" style={{ width: "34%", height: 10, borderRadius: 4 }} />
            <div className="shimmer" style={{ width: "88%", height: 13, borderRadius: 4 }} />
            <div className="shimmer" style={{ width: "60%", height: 13, borderRadius: 4 }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** transient status flash used across admin + settings */
export function Flash({ msg }: { msg: { text: string; type: "ok" | "err" } | null }) {
  if (!msg) return null;
  return (
    <div
      className="nifade"
      style={{
        padding: "8px 14px",
        borderRadius: "var(--radius)",
        border: `1px solid ${msg.type === "err" ? "var(--neg)" : "var(--posborder)"}`,
        background: msg.type === "err" ? "var(--negsoft)" : "var(--possoft)",
        color: msg.type === "err" ? "var(--neg)" : "var(--pos)",
        fontSize: 12,
        fontWeight: 550,
      }}
    >
      {msg.text}
    </div>
  );
}
