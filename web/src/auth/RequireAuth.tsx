import { type ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "@/auth/useAuth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <p>Lädt…</p>;
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
