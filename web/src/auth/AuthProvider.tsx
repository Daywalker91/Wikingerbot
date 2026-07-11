import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/api/client";
import { getMe, type CurrentUser } from "@/api/auth";
import { AuthContext } from "@/auth/AuthContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setUser(await getMe());
    } catch (error) {
      // 401 heisst schlicht "nicht eingeloggt" - kein Fehlerzustand, den man
      // dem Nutzer anzeigen muesste.
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
      } else {
        throw error;
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, loading, refresh }}>{children}</AuthContext.Provider>
  );
}
