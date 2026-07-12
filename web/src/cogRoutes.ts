import type { ComponentType } from "react";

export interface CogPageRoute {
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
// Zentral statt in App.tsx, damit auch die NavBar dieselbe Liste nutzen kann.
const cogPageModules = import.meta.glob("../../bot/cogs/*/web/*Page.tsx", {
  eager: true,
}) as Record<string, CogPageModule>;

const unordered = Object.values(cogPageModules).map((module) => ({
  ...module.route,
  Component: module.default,
}));

// Dashboard soll immer als Erstes in Nav und als Landing-Page nach dem Login
// erscheinen, unabhaengig von der (alphabetischen) Glob-Reihenfolge der
// Cog-Ordner - der Rest bleibt in der gefundenen Reihenfolge.
export const cogRoutes = [
  ...unordered.filter((route) => route.path === "/dashboard"),
  ...unordered.filter((route) => route.path !== "/dashboard"),
];
