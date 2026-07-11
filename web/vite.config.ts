import path from "path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Cog-Seiten (bot/cogs/*/web/*Page.tsx) liegen ausserhalb von web/ - jedes
// Cog ist eine in sich geschlossene Erweiterung (Discord-Commands, optionale
// FastAPI-Route UND optionale React-Seite liegen zusammen im Cog-Ordner,
// siehe CREATING_A_COG.md), statt hier zentral gesammelt zu werden.
export default defineConfig({
  // Explizit auf web/ gepinnt, unabhaengig vom Arbeitsverzeichnis, aus dem
  // `npm run dev` aufgerufen wird (package.json liegt bewusst im Repo-Root,
  // damit node_modules fuer bot/cogs/*/web/* auffindbar ist - siehe unten).
  root: __dirname,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    fs: {
      // erlaubt Vite, Dateien ausserhalb von web/ auszuliefern (bot/cogs/*/web/*)
      allow: [path.resolve(__dirname, ".."), path.resolve(__dirname, "./src")],
    },
  },
});
