"use client";

import { signIn }     from "next-auth/react";
import { useState }   from "react";
import { useRouter }  from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
  InputOTPSeparator,
} from "@/components/ui/input-otp";
import { Cpu } from "lucide-react";
import { encryptPayload } from "@/lib/crypto";
import { AppRoutes } from "@/app/api/routes";


export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [requires2FA, setRequires2FA] = useState(false);
  const [tempToken, setTempToken] = useState("");
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    if (!requires2FA) {
      // Phase 1: Call backend directly to check if 2FA is needed
      try {
        const encrypted = encryptPayload({
          username,
          password,
        });

        const res = await fetch("/api/backend-auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ encrypted }),
        });

        if (!res.ok) {
          setIsLoading(false);
          setError("Invalid username or password");
          return;
        }

        const data = await res.json();

        if (data.requires_2fa) {
          // 2FA is required — show TOTP input
          setTempToken(data.temp_token);
          setRequires2FA(true);
          setIsLoading(false);
          return;
        }

        // No 2FA — complete sign-in via NextAuth
        const result = await signIn("credentials", {
          username,
          password,
          redirect: false,
        });

        setIsLoading(false);

        if (result?.error) {
          setError("Invalid username or password");
        } else {
          router.push("/home");
          router.refresh();
        }
      } catch {
        setIsLoading(false);
        setError("Login failed. Please try again.");
      }
    } else {
      // Phase 2: Verify TOTP code, then complete sign-in
      try {
        const encrypted = encryptPayload({
          temp_token: tempToken,
          totp_code: totpCode,
        });

        const res = await fetch(AppRoutes.TOTPLoginVerify(), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ encrypted }),
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Invalid code" }));
          throw new Error(err.detail || "Verification failed");
        }

        // 2FA verified — now sign in with NextAuth including the TOTP code
        const result = await signIn("credentials", {
          username,
          password,
          totp_code: totpCode,
          redirect: false,
        });

        setIsLoading(false);

        if (result?.error) {
          setError("Authentication failed");
        } else {
          router.push("/home");
          router.refresh();
        }
      } catch (err: any) {
        setIsLoading(false);
        setError(err.message || "Invalid 2FA code");
      }
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="p-8 rounded-md border w-full max-w-md">
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
            <Cpu className="h-5 w-5 text-primary-foreground" />
          </div>
          <span className="text-xl font-bold tracking-tight">Obsidian AI</span>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {!requires2FA ? (
            <>
              <div>
                <label
                  htmlFor="username"
                  className="block text-sm font-medium  "
                >
                  Username
                </label>
                <input
                  type="text"
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="mt-1 block w-full px-3 py-2 border outline-none rounded-md focus:border-primary h-12"
                  required
                />
              </div>
              <div>
                <label
                  htmlFor="password"
                  className="block text-sm font-medium"
                >
                  Password
                </label>
                <input
                  type="password"
                  id="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="mt-1 block w-full px-3 py-2 border outline-none rounded-md focus:border-primary h-12"
                  required
                />
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground text-center">
                Enter the 6-digit code from your authenticator app
              </p>
              <div className="flex justify-center">
                <InputOTP
                  maxLength={6}
                  value={totpCode}
                  onChange={(value) => setTotpCode(value)}
                  autoFocus
                >
                  <InputOTPGroup>
                    <InputOTPSlot index={0} />
                    <InputOTPSlot index={1} />
                    <InputOTPSlot index={2} />
                  </InputOTPGroup>
                  <InputOTPSeparator />
                  <InputOTPGroup>
                    <InputOTPSlot index={3} />
                    <InputOTPSlot index={4} />
                    <InputOTPSlot index={5} />
                  </InputOTPGroup>
                </InputOTP>
              </div>
            </>
          )}

          {error && <p className="text-red-500 text-sm">{error}</p>}

          <Button
            type="submit"
            disabled={isLoading}
            className="h-12  cursor-pointer w-full disabled:opacity-50 disabled:cursor-not-allowed"
            variant={'outline'}
          >
            {isLoading
              ? requires2FA ? "Verifying..." : "Signing in..."
              : requires2FA ? "Verify" : "Sign In"}
          </Button>

          {requires2FA && (
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={() => {
                setRequires2FA(false);
                setTempToken("");
                setTotpCode("");
                setError("");
              }}
            >
              Back to login
            </Button>
          )}
        </form>

        {!requires2FA && (
          <p className="mt-4 text-center text-sm ">
            Don&apos;t have an account?{" "}
            <a href="/register" className="font-bold text-primary hover:underline">
              Register
            </a>
          </p>
        )}
      </div>
    </div>
  );
}
