// Spiegelt bot/cogs/amp/api.py's ServerStatusOut 1:1.
export interface ServerStatus {
  id: number;
  instance_name: string;
  display_name: string;
  host: string;
  reachable: boolean;
  state: string | null;
  uptime: string | null;
  players: [number, number] | null;
}
