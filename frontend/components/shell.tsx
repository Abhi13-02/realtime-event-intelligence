"use client";

// App shell per handoff: collapsible sidebar (214↔60px), 52px top bar with
// theme toggle + Tune popover, impersonation banner when an admin is
// acting as a user. LIVE-sources pill intentionally omitted; the pulsing
// dot reflects the real WebSocket connection instead.

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import {
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  ListMinus,
  LogOut,
  Moon,
  Settings,
  Shield,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { useTheme, DENSITY_LABELS } from "@/lib/theme";
import { useWebSocket } from "@/lib/websocket";
import { adminApi } from "@/lib/api";
import { initials } from "@/lib/format";

const NAV_MONITOR = [
  { href: "/", label: "Home Feed", icon: ListMinus },
  { href: "/topics", label: "Topics", icon: LayoutGrid },
];
const NAV_WORKSPACE = [
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/admin", label: "Admin", icon: Shield },
];

function readImpersonationCookie(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)impersonate_user_id=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function TunePopover({ onClose }: { onClose: () => void }) {
  const t = useTheme();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  const segBtn = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "6px 0",
    borderRadius: "var(--radiussm)",
    fontSize: 11.5,
    fontWeight: 600,
    border: active ? "1px solid transparent" : "1px solid var(--border)",
    background: active ? "var(--accent)" : "var(--bg2)",
    color: active ? "var(--accentfg)" : "var(--textmute)",
  });

  return (
    <div
      ref={ref}
      className="nifade"
      style={{
        position: "absolute",
        top: 56,
        right: 20,
        zIndex: 40,
        width: 264,
        background: "var(--panel)",
        border: "1px solid var(--border2)",
        borderRadius: "var(--radiuslg)",
        boxShadow: "var(--shadowlg)",
        padding: 16,
      }}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: 14 }}>
        <span className="text-ink" style={{ fontSize: 12, fontWeight: 600 }}>
          Appearance
        </span>
        <span className="text-mute font-mono" style={{ fontSize: 10 }}>
          runtime tokens
        </span>
      </div>
      <div className="flex" style={{ gap: 6, marginBottom: 16 }}>
        <button style={segBtn(t.theme === "dark")} onClick={() => t.setTheme("dark")}>
          Dark
        </button>
        <button style={segBtn(t.theme === "light")} onClick={() => t.setTheme("light")}>
          Light
        </button>
      </div>
      {[
        {
          label: "Accent hue",
          value: `${t.accentHue}°`,
          min: 150,
          max: 300,
          v: t.accentHue,
          set: t.setAccentHue,
          gradient:
            "linear-gradient(90deg,oklch(.65 .15 150),oklch(.65 .15 200),oklch(.65 .15 250),oklch(.65 .15 300))",
        },
        {
          label: "Density",
          value: DENSITY_LABELS[t.density - 1],
          min: 1,
          max: 5,
          v: t.density,
          set: t.setDensity,
        },
        {
          label: "Corner radius",
          value: `${t.radius}px`,
          min: 0,
          max: 16,
          v: t.radius,
          set: t.setRadius,
        },
      ].map((s, i, arr) => (
        <div key={s.label} style={{ marginBottom: i < arr.length - 1 ? 14 : 0 }}>
          <div className="flex justify-between" style={{ marginBottom: 7 }}>
            <span className="text-dim" style={{ fontSize: 11, fontWeight: 500 }}>
              {s.label}
            </span>
            <span className="text-mute font-mono" style={{ fontSize: 11 }}>
              {s.value}
            </span>
          </div>
          <input
            type="range"
            min={s.min}
            max={s.max}
            step={1}
            value={s.v}
            onChange={(e) => s.set(Number(e.target.value))}
            className="w-full"
            style={s.gradient ? { background: s.gradient } : undefined}
          />
        </div>
      ))}
    </div>
  );
}

function titleFor(pathname: string): string {
  if (pathname === "/") return "Home Feed";
  if (/^\/topics\/[^/]+\/n\//.test(pathname)) return "Narrative Timeline";
  if (/^\/topics\/[^/]+/.test(pathname)) return "Topic Deep Dive";
  if (pathname.startsWith("/topics")) return "Topics";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Narrative Intelligence";
}

export default function Shell({
  userName,
  children,
}: {
  userName: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const title = titleFor(pathname);
  const { theme, setTheme } = useTheme();
  const { isConnected } = useWebSocket();
  const [expanded, setExpanded] = useState(true);
  const [tuneOpen, setTuneOpen] = useState(false);
  const [impersonating, setImpersonating] = useState<string | null>(null);

  useEffect(() => {
    setImpersonating(readImpersonationCookie());
  }, []);

  const stopImpersonation = async () => {
    await adminApi.stopImpersonation();
    window.location.href = "/admin";
  };

  const navLink = (href: string, label: string, Icon: typeof ListMinus) => {
    const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
    return (
      <Link
        key={href}
        href={href}
        title={label}
        className="flex items-center transition-colors"
        style={{
          gap: 9,
          padding: expanded ? "7px 9px" : "7px 0",
          justifyContent: expanded ? "flex-start" : "center",
          borderRadius: "var(--radiussm)",
          background: active ? "var(--accentsoft)" : "transparent",
          color: active ? "var(--text)" : "var(--textdim)",
          fontSize: 12.5,
          fontWeight: active ? 600 : 500,
          whiteSpace: "nowrap",
        }}
      >
        <span
          className="grid place-items-center"
          style={{ width: 16, height: 16, flex: "none", color: active ? "var(--accent2)" : "var(--textmute)" }}
        >
          <Icon size={16} strokeWidth={1.55} />
        </span>
        {expanded && label}
      </Link>
    );
  };

  return (
    <div className="flex" style={{ minHeight: "100vh", background: "var(--bg)", color: "var(--text)" }}>
      <aside
        className="flex flex-col bg-bg2 border-r border-line"
        style={{
          width: expanded ? 214 : 60,
          flex: "none",
          height: "100vh",
          position: "sticky",
          top: 0,
          zIndex: 10,
          overflow: "hidden",
          transition: "width .16s ease",
        }}
      >
        <div className="flex items-center border-b border-line" style={{ gap: 9, padding: "13px 15px" }}>
          <div
            className="grid place-items-center bg-accent text-accentfg"
            style={{ width: 24, height: 24, borderRadius: 7, fontWeight: 700, fontSize: 14, flex: "none" }}
          >
            N
          </div>
          {expanded && (
            <>
              <div className="flex-1 min-w-0">
                <div className="text-ink" style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.1, whiteSpace: "nowrap" }}>
                  Narrative
                </div>
                <div className="text-mute uppercase" style={{ fontSize: 9.5, letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                  Intelligence
                </div>
              </div>
              <div
                className={isConnected ? "nipulse" : ""}
                title={isConnected ? "Live — connected" : "Disconnected"}
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: isConnected ? "var(--pos)" : "var(--textmute)",
                  boxShadow: isConnected ? "0 0 0 3px var(--possoft)" : "none",
                  flex: "none",
                }}
              />
            </>
          )}
        </div>

        <button
          onClick={() => setExpanded(!expanded)}
          title="Toggle sidebar"
          className="flex items-center text-mute hover:text-ink transition-colors"
          style={{
            gap: 9,
            padding: expanded ? "9px 17px" : "9px 0",
            justifyContent: expanded ? "flex-start" : "center",
            fontSize: 11.5,
            fontWeight: 550,
            background: "transparent",
            border: "none",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span className="grid place-items-center" style={{ width: 16, height: 16, flex: "none" }}>
            {expanded ? <ChevronLeft size={15} strokeWidth={1.55} /> : <ChevronRight size={15} strokeWidth={1.55} />}
          </span>
          {expanded && "Collapse"}
        </button>

        <nav className="flex flex-col flex-1" style={{ padding: "8px 8px 4px", gap: 1, overflow: "auto" }}>
          {expanded && (
            <div className="eyebrow" style={{ letterSpacing: ".07em", padding: "8px 9px 5px", whiteSpace: "nowrap" }}>
              Monitor
            </div>
          )}
          {NAV_MONITOR.map((n) => navLink(n.href, n.label, n.icon))}
          {expanded && (
            <div className="eyebrow" style={{ letterSpacing: ".07em", padding: "14px 9px 5px", whiteSpace: "nowrap" }}>
              Workspace
            </div>
          )}
          {NAV_WORKSPACE.map((n) => navLink(n.href, n.label, n.icon))}
        </nav>

        <div className="flex items-center border-t border-line" style={{ padding: "9px 10px", gap: 9 }}>
          <div
            className="grid place-items-center bg-panel2 border border-line2 text-dim"
            style={{ width: 27, height: 27, borderRadius: 7, fontSize: 11, fontWeight: 600, flex: "none" }}
          >
            {initials(userName)}
          </div>
          {expanded && (
            <>
              <div className="flex-1 min-w-0">
                <div className="text-ink truncate" style={{ fontSize: 11.5, fontWeight: 550 }}>
                  {userName}
                </div>
                <div className="text-mute" style={{ fontSize: 10 }}>
                  Analyst
                </div>
              </div>
              <button
                onClick={() => signOut({ callbackUrl: "/login" })}
                title="Sign out"
                className="grid place-items-center text-mute hover:text-ink hover:bg-panel transition-colors"
                style={{ padding: 4, borderRadius: 5, flex: "none", border: "none", background: "transparent" }}
              >
                <LogOut size={15} strokeWidth={1.55} />
              </button>
            </>
          )}
        </div>
      </aside>

      <main className="flex-1 min-w-0 flex flex-col" style={{ height: "100vh", overflow: "hidden" }}>
        {impersonating && (
          <div
            className="flex items-center justify-between"
            style={{ flex: "none", background: "var(--neg)", color: "#fff", padding: "6px 20px", fontSize: 11.5, fontWeight: 600 }}
          >
            <span className="font-mono">IMPERSONATION ACTIVE · {impersonating}</span>
            <button
              onClick={stopImpersonation}
              style={{
                background: "#fff",
                color: "var(--neg)",
                border: "none",
                borderRadius: 5,
                padding: "3px 10px",
                fontSize: 11,
                fontWeight: 700,
              }}
            >
              EXIT & BACK TO ADMIN
            </button>
          </div>
        )}
        <header
          className="flex items-center border-b border-line bg-bg"
          style={{ flex: "none", height: 52, gap: 14, padding: "0 20px", position: "relative", zIndex: 20 }}
        >
          <div className="text-ink truncate" style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.15 }}>
            {title}
          </div>
          <div className="flex-1" />
          <div className="flex items-center" style={{ gap: 6, padding: "5px 10px", borderRadius: 99, background: isConnected ? "var(--possoft)" : "var(--neusoft)", border: `1px solid ${isConnected ? "var(--posborder)" : "var(--border)"}` }}>
            <div className={isConnected ? "nipulse" : ""} style={{ width: 6, height: 6, borderRadius: "50%", background: isConnected ? "var(--pos)" : "var(--textmute)" }} />
            <span style={{ fontSize: 10.5, fontWeight: 600, color: isConnected ? "var(--pos)" : "var(--textmute)", letterSpacing: ".02em" }}>
              {isConnected ? "LIVE" : "OFFLINE"}
            </span>
          </div>
          <div style={{ width: 1, height: 22, background: "var(--border)" }} />
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title="Toggle theme"
            className="grid place-items-center bg-bg2 border border-line text-dim hover:text-ink transition-colors"
            style={{ width: 30, height: 30, borderRadius: "var(--radius)" }}
          >
            {theme === "dark" ? <Sun size={15} strokeWidth={1.55} /> : <Moon size={15} strokeWidth={1.55} />}
          </button>
          <button
            onClick={() => setTuneOpen(!tuneOpen)}
            className="flex items-center bg-bg2 border border-line text-dim hover:text-ink transition-colors"
            style={{ height: 30, padding: "0 11px", borderRadius: "var(--radius)", gap: 7, fontSize: 12, fontWeight: 550 }}
          >
            <SlidersHorizontal size={14} strokeWidth={1.55} />
            <span>Tune</span>
          </button>
        </header>
        {tuneOpen && <TunePopover onClose={() => setTuneOpen(false)} />}
        <div className="flex-1" style={{ overflow: "auto", position: "relative" }}>
          {children}
        </div>
      </main>
    </div>
  );
}
