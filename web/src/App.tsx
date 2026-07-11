import type { ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthProvider";
import { RequireAuth } from "@/auth/RequireAuth";
import Login from "@/pages/Login";

interface CogPageRoute {
  path: string;
  navLabel: string;
}

interface CogPageModule {
  default: ComponentType;
  route: CogPageRoute;
}

// Sammelt jede bot/cogs/<cog>/web/<Name>Page.tsx automatisch ein - eine neue
// Cog-Seite braucht dafuer KEINE Aenderung hier, nur die Datei muss existieren
// und `route`+einen default export bereitstellen (siehe CREATING_A_COG.md).
const cogPageModules = import.meta.glob("../../bot/cogs/*/web/*Page.tsx", {
  eager: true,
}) as Record<string, CogPageModule>;

const cogRoutes = Object.values(cogPageModules).map((module) => ({
  ...module.route,
  Component: module.default,
}));

export default function App() {
  const firstCogPath = cogRoutes[0]?.path ?? "/login";

  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Navigate to={firstCogPath} replace />} />
        <Route path="/login" element={<Login />} />
        {cogRoutes.map(({ path, Component }) => (
          <Route
            key={path}
            path={path}
            element={
              <RequireAuth>
                <Component />
              </RequireAuth>
            }
          />
        ))}
      </Routes>
    </AuthProvider>
  );
}
