import type { Metadata } from "next";
import LoginForm from "@/features/auth/components/LoginForm";

export const metadata: Metadata = {
  title: "Admin Login | ToolNet Publisher",
  robots: {
    index: false,
    follow: false,
  },
};

export default function LoginPage() {
  return <LoginForm />;
}
