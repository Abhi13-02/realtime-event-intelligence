"use client";

// Admin sign-in — the key is validated server-side and stored in an
// httpOnly cookie by /api/admin-session; it never enters client JS state
// beyond this form submission.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import AuthCard from "@/components/auth-card";
import { Input, Label } from "@/components/ui";
import { adminApi } from "@/lib/api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;
    setLoading(true);
    setError("");
    try {
      await adminApi.signIn(key.trim());
      router.push("/admin");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthCard>
      <div className="flex items-center" style={{ gap: 8, marginBottom: 3 }}>
        <ShieldCheck size={16} strokeWidth={1.55} className="text-accent2" />
        <span className="text-ink" style={{ fontSize: 15, fontWeight: 600 }}>
          Admin console
        </span>
      </div>
      <div className="text-mute" style={{ fontSize: 12.5, marginBottom: 22 }}>
        Operator access — enter the admin secret key.
      </div>
      <form onSubmit={submit}>
        <Label>Admin secret key</Label>
        <Input
          type="password"
          required
          autoFocus
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="Enter your admin key…"
          style={{ marginBottom: 8 }}
        />
        {error && (
          <div className="text-neg" style={{ fontSize: 12, marginBottom: 8 }}>
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={loading || !key.trim()}
          className="w-full bg-accent text-accentfg hover:bg-accent2 transition-colors disabled:opacity-50"
          style={{ padding: 10, borderRadius: "var(--radius)", border: "none", fontSize: 13, fontWeight: 600, marginTop: 10 }}
        >
          {loading ? "Authenticating…" : "Access console"}
        </button>
      </form>
    </AuthCard>
  );
}
