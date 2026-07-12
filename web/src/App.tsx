import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthProvider";
import { RequireAuth } from "@/auth/RequireAuth";
import { cogRoutes } from "@/cogRoutes";
import { NavBar } from "@/components/NavBar";
import Login from "@/pages/Login";

export default function App() {
  const landingPath = cogRoutes.find((route) => route.path === "/dashboard")?.path ?? cogRoutes[0]?.path ?? "/login";

  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Navigate to={landingPath} replace />} />
        <Route path="/login" element={<Login />} />
        {cogRoutes.map(({ path, Component }) => (
          <Route
            key={path}
            path={path}
            element={
              <RequireAuth>
                <NavBar />
                <Component />
              </RequireAuth>
            }
          />
        ))}
      </Routes>
    </AuthProvider>
  );
}
