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

export interface ServerActionResult {
  ok: boolean;
  message: string;
}

export interface ConsoleLineItem {
  contents: string;
  source: string;
  type: string;
}

export interface DiscoverableInstance {
  instance_id: string;
  friendly_name: string;
  module: string;
  running: boolean;
  port: number | null;
}

export interface AddressSettings {
  game_host: string;
  effective_host: string | null;
  public_host: string | null;
}

export interface ServerCreateBody {
  instance_name: string;
  amp_instance_id: string;
  display_name: string;
  host: string;
}
