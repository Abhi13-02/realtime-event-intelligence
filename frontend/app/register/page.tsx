"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { signIn } from "next-auth/react";
import AuthCard from "@/components/auth-card";
import { Input, Label } from "@/components/ui";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    const res = await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(body.detail ?? body.error ?? "Registration failed.");
      setLoading(false);
      return;
    }

    // Account created — sign straight in with the same credentials.
    const signed = await signIn("credentials", { email, password, redirect: false });
    setLoading(false);
    if (signed?.error) {
      router.push("/login");
      return;
    }
    router.push("/");
    router.refresh();
  };

  return (
    <AuthCard>
      <div className="text-ink" style={{ fontSize: 15, fontWeight: 600, marginBottom: 3 }}>
        Create your workspace
      </div>
      <div className="text-mute" style={{ fontSize: 12.5, marginBottom: 22 }}>
        Track topics and get narrative alerts in real time.
      </div>
      <form onSubmit={submit}>
        <Label>Full name</Label>
        <Input
          required
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ marginBottom: 14 }}
        />
        <Label>Work email</Label>
        <Input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ marginBottom: 14 }}
        />
        <Label>Password</Label>
        <Input
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ marginBottom: 8 }}
        />
        <div className="text-mute" style={{ fontSize: 11, marginBottom: 8 }}>
          At least 8 characters.
        </div>
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
            marginTop: 10,
          }}
        >
          {loading ? "Creating account…" : "Create account"}
        </button>
      </form>
      <div className="text-center" style={{ marginTop: 18, fontSize: 12 }}>
        <span className="text-mute">Already have an account? </span>
        <Link href="/login" className="text-accent2" style={{ fontWeight: 550 }}>
          Sign in
        </Link>
      </div>
    </AuthCard>
  );
}
