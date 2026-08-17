"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { signIn } from "next-auth/react";
import AuthCard from "@/components/auth-card";
import { Input, Label } from "@/components/ui";

// Public read-only-ish demo account, seeded with topics that already have
// matched articles and discovered narratives. Deliberately hardcoded: the
// point is that a visitor can look around without signing up.
const DEMO_EMAIL = "demo@abhinavdev.online";
const DEMO_PASSWORD = "DemoPass123";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);

  const authenticate = async (withEmail: string, withPassword: string) => {
    setError("");
    const res = await signIn("credentials", {
      email: withEmail,
      password: withPassword,
      redirect: false,
    });
    if (res?.error) {
      setError("Invalid email or password.");
      return false;
    }
    router.push("/feed");
    router.refresh();
    return true;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    await authenticate(email, password);
    setLoading(false);
  };

  const enterDemo = async () => {
    setDemoLoading(true);
    const ok = await authenticate(DEMO_EMAIL, DEMO_PASSWORD);
    if (!ok) setDemoLoading(false);
  };

  return (
    <AuthCard>
      <div className="text-ink" style={{ fontSize: 15, fontWeight: 600, marginBottom: 3 }}>
        Sign in to your workspace
      </div>
      <div className="text-mute" style={{ fontSize: 12.5, marginBottom: 22 }}>
        Monitor emerging narratives in real time.
      </div>
      <form onSubmit={submit}>
        <Label>Work email</Label>
        <Input
          type="email"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ marginBottom: 14 }}
        />
        <Label>Password</Label>
        <Input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ marginBottom: 8 }}
        />
        {error && (
          <div className="text-neg" style={{ fontSize: 12, marginBottom: 8 }}>
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-accent text-accentfg hover:bg-accent2 transition-colors disabled:opacity-50"
          style={{
            padding: 10,
            borderRadius: "var(--radius)",
            border: "none",
            fontSize: 13,
            fontWeight: 600,
            letterSpacing: ".01em",
            marginTop: 10,
          }}
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <div className="flex items-center" style={{ gap: 10, margin: "18px 0" }}>
        <div className="flex-1" style={{ height: 1, background: "var(--border)" }} />
        <span className="text-mute uppercase" style={{ fontSize: 10.5, letterSpacing: ".05em" }}>
          or
        </span>
        <div className="flex-1" style={{ height: 1, background: "var(--border)" }} />
      </div>
      <button
        type="button"
        onClick={enterDemo}
        disabled={demoLoading}
        className="flex w-full items-center justify-center bg-accentsoft text-ink border border-accent hover:bg-panel2 transition-colors disabled:opacity-50"
        style={{
          padding: 9,
          borderRadius: "var(--radius)",
          fontSize: 12.5,
          fontWeight: 600,
          marginBottom: 9,
          cursor: "pointer",
        }}
      >
        {demoLoading ? "Opening demo…" : "Explore the live demo — no signup"}
      </button>
      <Link
        href="/register"
        className="flex w-full items-center justify-center bg-bg2 text-ink border border-line2 hover:bg-panel2 transition-colors"
        style={{ padding: 9, borderRadius: "var(--radius)", fontSize: 12.5, fontWeight: 550 }}
      >
        Create an account
      </Link>
      <div className="text-mute" style={{ fontSize: 11, marginTop: 12, textAlign: "center" }}>
        Demo account · {DEMO_EMAIL} / {DEMO_PASSWORD}
      </div>
    </AuthCard>
  );
}
