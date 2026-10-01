import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <title>Sign in · JB Hi-Fi</title>
      <SignIn />
    </main>
  );
}
