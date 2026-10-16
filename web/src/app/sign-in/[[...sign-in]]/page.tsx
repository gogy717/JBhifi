import { SignIn } from "@clerk/nextjs";

import { AuthFrame, clerkAppearance } from "@/components/shop/auth-frame";

export default function SignInPage() {
  return (
    <AuthFrame title="Welcome back.">
      <title>Sign in · TechLight</title>
      <SignIn appearance={clerkAppearance} />
    </AuthFrame>
  );
}
