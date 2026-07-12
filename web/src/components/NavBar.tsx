import { NavLink } from "react-router-dom";

import { logout } from "@/api/auth";
import { cogRoutes } from "@/cogRoutes";

export function NavBar() {
  async function handleLogout() {
    await logout();
    window.location.href = "/login";
  }

  return (
    <nav
      style={{
        display: "flex",
        alignItems: "center",
        gap: 20,
        padding: "12px 24px",
        borderBottom: "1px solid #444",
      }}
    >
      {cogRoutes.map((route) => (
        <NavLink
          key={route.path}
          to={route.path}
          style={({ isActive }) => ({
            textDecoration: "none",
            color: "inherit",
            fontWeight: isActive ? "bold" : "normal",
          })}
        >
          {route.navLabel}
        </NavLink>
      ))}
      <button onClick={() => void handleLogout()} style={{ marginLeft: "auto" }}>
        Logout
      </button>
    </nav>
  );
}
