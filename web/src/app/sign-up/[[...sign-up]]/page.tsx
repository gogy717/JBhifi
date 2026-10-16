import { SignUp } from "@clerk/nextjs";
import Link from "next/link";

import { LogoMark, Wordmark } from "@/components/brand";

export default function SignUpPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-4">
      <title>Create an account · TechLight</title>
      <Link href="/" className="flex items-center gap-2.5 text-ink" aria-label="TechLight home">
        <LogoMark className="h-10 w-10" />
        <Wordmark className="text-3xl" />
      </Link>
      <SignUp />
    </main>
  );
}
