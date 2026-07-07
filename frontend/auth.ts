import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000/v1";

export interface BackendUser {
  id: string;
  name: string;
  email: string;
  phone_number: string | null;
  created_at: string;
}

declare module "next-auth" {
  interface Session {
    accessToken: string;
    user: {
      id: string;
      name: string;
      email: string;
    };
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt", maxAge: 7 * 24 * 60 * 60 },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: {
        email: {},
        password: {},
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;

        const res = await fetch(`${BACKEND_URL}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: credentials.email,
            password: credentials.password,
          }),
        });
        if (!res.ok) return null;

        const data: { access_token: string; user: BackendUser } = await res.json();
        return {
          id: data.user.id,
          name: data.user.name,
          email: data.user.email,
          accessToken: data.access_token,
        };
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        token.accessToken = (user as { accessToken?: string }).accessToken;
        token.userId = user.id;
      }
      return token;
    },
    session({ session, token }) {
      session.accessToken = token.accessToken as string;
      if (session.user && token.userId) {
        session.user.id = token.userId as string;
      }
      return session;
    },
  },
});
