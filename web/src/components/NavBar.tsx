import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { logout } from "@/api/auth";
import { cogRoutes } from "@/cogRoutes";

const HOME_PATH = "/dashboard";

/**
 * Haus-Symbol fuer die Startseite (Dashboard), alle anderen Seiten in einer
 * Dropdown-Liste - mit jedem neuen Cog wuerde eine Zeile mit allen Eintraegen
 * sonst ueberlaufen. Die Liste kommt weiter automatisch aus cogRoutes.
 */
export function NavBar() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const home = cogRoutes.find((route) => route.path === HOME_PATH);
  const pages = cogRoutes
    .filter((route) => route.path !== HOME_PATH)
    .sort((a, b) => a.navLabel.localeCompare(b.navLabel, "de"));
  const current = pages.find((route) => location.pathname.startsWith(route.path));

  // Nach jedem Seitenwechsel zu
  useEffect(() => setOpen(false), [location.pathname]);

  // Klick daneben oder Escape schliesst
  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function handleLogout() {
    await logout();
    window.location.href = "/login";
  }

  return (
    <nav className="wb-nav">
      {home && (
        <Link
          to={home.path}
          className={`wb-nav-home${location.pathname.startsWith(home.path) ? " active" : ""}`}
          title={home.navLabel}
          aria-label={home.navLabel}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1z" fill="currentColor" />
          </svg>
        </Link>
      )}

      <div className="wb-nav-menu" ref={menuRef}>
        <button
          type="button"
          className="wb-nav-toggle"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          ☰ {current?.navLabel ?? "Menü"} <span aria-hidden="true">▾</span>
        </button>
        {open && (
          <div className="wb-nav-dropdown" role="menu">
            {pages.map((route) => (
              <NavLink key={route.path} to={route.path} role="menuitem">
                {route.navLabel}
              </NavLink>
            ))}
          </div>
        )}
      </div>

      <button onClick={() => void handleLogout()} style={{ marginLeft: "auto" }}>
        Logout
      </button>
    </nav>
  );
}
