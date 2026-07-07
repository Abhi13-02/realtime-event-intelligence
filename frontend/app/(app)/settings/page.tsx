"use client";

// Settings — profile card per handoff. Real fields from the backend:
// display name + phone number (E.164, used for SMS alerts). Email is
// read-only (it is the login identity). Per-topic delivery channels live
// in the topic modal, matching the old frontend.

import { useEffect, useState } from "react";
import { Input, Label } from "@/components/ui";
import { api } from "@/lib/api";
import { initials } from "@/lib/format";

export default function SettingsPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"ok" | "err" | null>(null);
  const [errText, setErrText] = useState("");

  useEffect(() => {
    api
      .getMe()
      .then((me) => {
        setName(me.name ?? "");
        setEmail(me.email ?? "");
        setPhone(me.phone_number ?? "");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      await api.updateMe({ name, phone_number: phone.trim() || null });
      setStatus("ok");
      setTimeout(() => setStatus(null), 3000);
    } catch (err) {
      setErrText(err instanceof Error ? err.message : "Save failed.");
      setStatus("err");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="grid place-items-center text-mute" style={{ height: "100%", fontSize: 13 }}>
        Loading…
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "22px 24px 44px" }}>
      <form onSubmit={save}>
        <section
          className="bg-panel border border-line"
          style={{ borderRadius: "var(--radius)", padding: 20, marginBottom: 16 }}
        >
          <div className="text-ink" style={{ fontSize: 13, fontWeight: 600, marginBottom: 16 }}>
            Profile
          </div>
          <div className="flex items-center" style={{ gap: 14, marginBottom: 18 }}>
            <div
              className="grid place-items-center bg-accentsoft border border-line2"
              style={{ width: 52, height: 52, borderRadius: 14, fontSize: 17, fontWeight: 600, color: "var(--accent2)" }}
            >
              {initials(name)}
            </div>
            <div className="flex-1">
              <div className="text-ink" style={{ fontSize: 14, fontWeight: 600 }}>
                {name || "—"}
              </div>
              <div className="text-mute" style={{ fontSize: 12 }}>
                {email}
              </div>
            </div>
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div>
              <Label>Full name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div>
              <Label>Email</Label>
              <Input value={email} disabled style={{ opacity: 0.6 }} />
            </div>
          </div>
        </section>

        <section
          className="bg-panel border border-line"
          style={{ borderRadius: "var(--radius)", padding: 20, marginBottom: 20 }}
        >
          <div className="text-ink" style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
            SMS delivery
          </div>
          <div className="text-mute" style={{ fontSize: 11.5, marginBottom: 14 }}>
            Phone number used for topics with the SMS channel enabled.
            E.164 format, e.g. +919876543210.
          </div>
          <div style={{ maxWidth: 260 }}>
            <Label>Phone number</Label>
            <Input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+15550000000"
            />
          </div>
        </section>

        <div className="flex items-center justify-end" style={{ gap: 12 }}>
          {status === "ok" && (
            <span className="nifade" style={{ fontSize: 12, color: "var(--pos)", fontWeight: 550 }}>
              ✓ Preferences saved
            </span>
          )}
          {status === "err" && (
            <span className="nifade" style={{ fontSize: 12, color: "var(--neg)", fontWeight: 550 }}>
              {errText}
            </span>
          )}
          <button
            type="submit"
            disabled={saving}
            className="bg-accent text-accentfg hover:bg-accent2 transition-colors disabled:opacity-50"
            style={{ height: 33, padding: "0 18px", borderRadius: "var(--radius)", border: "none", fontSize: 12.5, fontWeight: 600 }}
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </div>
  );
}
