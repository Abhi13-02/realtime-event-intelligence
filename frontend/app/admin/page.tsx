"use client";

// Admin console — separate protected route with its own key-based session.
// Four tabs carrying every feature of the old admin panel, restyled in the
// Narrative Intelligence design system.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Moon, ShieldCheck, Sun } from "lucide-react";
import UsersTab from "@/components/admin/users-tab";
import IngestionTab from "@/components/admin/ingestion-tab";
import SystemTab from "@/components/admin/system-tab";
import DataTab from "@/components/admin/data-tab";
import { adminApi } from "@/lib/api";
import { useTheme } from "@/lib/theme";

const TABS = ["Users", "Ingestion", "System", "Data"] as const;
type Tab = (typeof TABS)[number];

export default function AdminPage() {
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [tab, setTab] = useState<Tab>("Users");

  const signOut = async () => {
    await adminApi.signOut();
    router.push("/admin/login");
    router.refresh();
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", color: "var(--text)" }}>
      {/* top bar */}
      <header
        className="flex items-center border-b border-line bg-bg"
        style={{ height: 52, gap: 14, padding: "0 20px", position: "sticky", top: 0, zIndex: 20 }}
      >
        <div className="flex items-center" style={{ gap: 9 }}>
          <div
            className="grid place-items-center bg-accent text-accentfg"
            style={{ width: 24, height: 24, borderRadius: 7 }}
          >
            <ShieldCheck size={14} strokeWidth={1.8} />
          </div>
          <div>
            <div className="text-ink" style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.1 }}>
              Admin console
            </div>
            <div className="text-mute uppercase" style={{ fontSize: 9.5, letterSpacing: ".06em" }}>
              Narrative Intelligence
            </div>
          </div>
        </div>
        <div className="flex-1" />
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          title="Toggle theme"
          className="grid place-items-center bg-bg2 border border-line text-dim hover:text-ink transition-colors"
          style={{ width: 30, height: 30, borderRadius: "var(--radius)" }}
        >
          {theme === "dark" ? <Sun size={15} strokeWidth={1.55} /> : <Moon size={15} strokeWidth={1.55} />}
        </button>
        <button
          onClick={signOut}
          className="text-mute hover:text-neg transition-colors"
          style={{ fontSize: 11.5, fontWeight: 600, background: "transparent", border: "none" }}
        >
          Sign out
        </button>
      </header>

      {/* tab bar */}
      <div className="border-b border-line" style={{ padding: "0 20px" }}>
        <div className="flex" style={{ gap: 2, maxWidth: 1080, margin: "0 auto" }}>
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="transition-colors"
              style={{
                padding: "12px 18px",
                fontSize: 12,
                fontWeight: 600,
                background: "transparent",
                border: "none",
                borderBottom: `2px solid ${tab === t ? "var(--accent)" : "transparent"}`,
                color: tab === t ? "var(--accent2)" : "var(--textmute)",
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <main style={{ maxWidth: 1080, margin: "0 auto", padding: "22px 24px 44px" }}>
        {tab === "Users" && <UsersTab />}
        {tab === "Ingestion" && <IngestionTab />}
        {tab === "System" && <SystemTab />}
        {tab === "Data" && <DataTab />}
      </main>
    </div>
  );
}
