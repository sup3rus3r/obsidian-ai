import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { encryptPayload } from "@/lib/crypto-server";

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Credentials({
      name: "Credentials",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
        totp_code: { label: "TOTP Code", type: "text" },
      },
      async authorize(credentials) {
        if (!credentials?.username || !credentials?.password) {
          return null;
        }

        try {
          const payload: Record<string, string> = {
            username: credentials.username as string,
            password: credentials.password as string,
          };
          if (credentials.totp_code) {
            payload.totp_code = credentials.totp_code as string;
          }

          const encryptedData = encryptPayload(payload);

          const res = await fetch("http://localhost:8000/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ encrypted: encryptedData }),
          });

          if (!res.ok) {
            return null;
          }

          const data = await res.json();

          // If 2FA is required but no totp_code was provided, reject
          // (the login page handles 2FA detection via direct API call)
          if (data.requires_2fa) {
            return null;
          }

          return {
            id: data.user.id.toString(),
            name: data.user.username,
            email: data.user.email,
            role: data.user.role,
            accessToken: data.access_token,
          };
        } catch (error) {
          console.error("Auth error:", error);
          return null;
        }
      },
    }),
  ],
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async jwt({ token, user, trigger, session }) {
      if (user) {
        token.id = user.id;
        token.role = user.role;
        token.accessToken = user.accessToken;
      }
      if (trigger === "update" && session) {
        if (session.role) {
          token.role = session.role;
        }
        if (session.accessToken) {
          token.accessToken = session.accessToken;
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.id = token.id as string;
        session.user.role = token.role as string;
      }
      session.accessToken = token.accessToken as string;
      return session;
    },
  },
});
