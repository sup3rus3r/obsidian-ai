"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { encryptPayload } from "@/lib/crypto";
import { Button } from "@/components/ui/button";
import { Cpu } from "lucide-react";
import Logo from "@/components/ui/logo";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const encryptedData = encryptPayload({ username, email, password });

      const res = await fetch("http://localhost:8000/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ encrypted: encryptedData }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Registration failed");
      }

      router.push("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center ">
      <div className=" p-8 rounded-md border w-full max-w-md">
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <Logo className={'h-8'}/>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="username"
              className="block text-sm font-medium"
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
              htmlFor="email"
              className="block text-sm font-medium"
            >
              Email
            </label>
            <input
              type="email"
              id="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
          {error && <p className="text-red-500 text-sm">{error}</p>}
          <Button
            type="submit"
            disabled={isLoading}
            className="h-12 w-full cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            variant={'outline'}
          >
            {isLoading ? "Creating account..." : "Register"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm">
          Already have an account?{" "}
          <a href="/login" className="font-bold text-primary hover:underline">
            Login
          </a>
        </p>
      </div>
    </div>
  );
}
