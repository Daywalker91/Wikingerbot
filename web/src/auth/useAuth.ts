import { useContext } from "react";

import { AuthContext, type AuthContextValue } from "@/auth/AuthContext";

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === undefined) {
    throw new Error("useAuth muss innerhalb von <AuthProvider> verwendet werden");
  }
  return value;
}
