import { SignUp } from "@clerk/nextjs";

import { AuthFrame, clerkAppearance } from "@/components/shop/auth-frame";

export default function SignUpPage() {
  return (
    <AuthFrame title="Make it yours.">
      <title>Create an account · TechLight</title>
      <SignUp appearance={clerkAppearance} />
    </AuthFrame>
  );
}
