import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <title>Create an account · JB Hi-Fi</title>
      <SignUp />
    </main>
  );
}
