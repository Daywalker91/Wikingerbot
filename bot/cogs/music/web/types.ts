export interface TrackItem {
  title: string;
  label: string;
}

export interface MusicState {
  connected: boolean;
  channel_id: string | null;
  channel_name: string | null;
  paused: boolean;
  current: TrackItem | null;
  queue: TrackItem[];
  queue_length: number;
  volume: number;
  my_channel_name: string | null;
  can_control: boolean;
}

export interface StationItem {
  name: string;
  category: string; // "" = ohne Kategorie
}

export interface Library {
  stations: StationItem[];
  files: string[];
  folders: string[];
  podcasts: string[];
}

export interface EpisodeItem {
  index: number;
  title: string;
  published: string;
}

export interface MusicConfig {
  stations: (StationItem & { url: string })[];
  podcasts: { name: string; url: string; channel_id: string | null }[];
  text_channels: { id: string; name: string }[];
  music_dir: string;
  file_count: number;
}

export type PlayKind = "radio" | "file" | "folder" | "podcast";
export type ControlAction = "pause" | "resume" | "skip" | "stop" | "shuffle" | "volume";
