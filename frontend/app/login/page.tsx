"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { signIn } from "next-auth/react";
import AuthCard from "@/components/auth-card";
import { Input, Label } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    const res = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });
    setLoading(false);
    if (res?.error) {
      setError("Invalid email or password.");
      return;
    }
    router.push("/");
    router.refresh();
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
      <Link
        href="/register"
        className="flex w-full items-center justify-center bg-bg2 text-ink border border-line2 hover:bg-panel2 transition-colors"
        style={{ padding: 9, borderRadius: "var(--radius)", fontSize: 12.5, fontWeight: 550 }}
      >
        Create an account
      </Link>
    </AuthCard>
  );
}
