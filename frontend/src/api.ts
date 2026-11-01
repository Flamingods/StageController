import type { ButtonAction } from './buttonGesture';
import type { Sequence as PillarSequence, Slot } from './pillar/types';
import type { ShowSpec } from './show/events';
import type { SongMapInfo } from './show/timeline';
import type { Tunable } from './show/tunables';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8000/api' : '/api';

export interface Song {
  id: number;
  title: string;
  artist: string;
  album: string;
  duration: number;
  filename: string;
  file_size: number;
  format: string;
  created_at: string;
}

export interface Playlist {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  song_count: number;
  total_duration: number;
}

export interface PlaylistDetail {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  songs: Song[];
}

export const songsApi = {
  getAll: async (params?: { search?: string; sort_by?: string; sort_desc?: boolean }): Promise<{ songs: Song[]; total: number }> => {
    const query = new URLSearchParams();
    if (params?.search) query.set('search', params.search);
    if (params?.sort_by) query.set('sort_by', params.sort_by);
    if (params?.sort_desc !== undefined) query.set('sort_desc', String(params.sort_desc));
    const res = await fetch(`${API_BASE}/songs?${query}`);
    return res.json();
  },

  upload: async (file: File): Promise<Song> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/songs/upload`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },

  uploadBatch: async (files: File[]): Promise<Song[]> => {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    const res = await fetch(`${API_BASE}/songs/upload/batch`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },

  update: async (id: number, data: { title?: string; artist?: string; album?: string }): Promise<Song> => {
    const res = await fetch(`${API_BASE}/songs/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  delete: async (id: number): Promise<void> => {
    await fetch(`${API_BASE}/songs/${id}`, { method: 'DELETE' });
  },

  getStreamUrl: (id: number): string => `${API_BASE}/songs/${id}/stream`,
};

export const playlistsApi = {
  getAll: async (): Promise<Playlist[]> => {
    const res = await fetch(`${API_BASE}/playlists`);
    return res.json();
  },

  get: async (id: number): Promise<PlaylistDetail> => {
    const res = await fetch(`${API_BASE}/playlists/${id}`);
    return res.json();
  },

  create: async (data: { name: string; description?: string }): Promise<Playlist> => {
    const res = await fetch(`${API_BASE}/playlists`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  update: async (id: number, data: { name?: string; description?: string }): Promise<Playlist> => {
    const res = await fetch(`${API_BASE}/playlists/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  delete: async (id: number): Promise<void> => {
    await fetch(`${API_BASE}/playlists/${id}`, { method: 'DELETE' });
  },

  addSongs: async (id: number, songIds: number[]): Promise<void> => {
    await fetch(`${API_BASE}/playlists/${id}/songs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_ids: songIds }),
    });
  },

  removeSongs: async (id: number, songIds: number[]): Promise<void> => {
    await fetch(`${API_BASE}/playlists/${id}/songs`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_ids: songIds }),
    });
  },

  reorder: async (id: number, songIds: number[]): Promise<void> => {
    await fetch(`${API_BASE}/playlists/${id}/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_ids: songIds }),
    });
  },

  shuffle: async (id: number): Promise<void> => {
    await fetch(`${API_BASE}/playlists/${id}/shuffle`, { method: 'POST' });
  },

  duplicate: async (id: number): Promise<Playlist> => {
    const res = await fetch(`${API_BASE}/playlists/${id}/duplicate`, { method: 'POST' });
    return res.json();
  },
};

export interface Device {
  id: number;
  name: string;
  ip_address: string;
  role: string;
  is_on: boolean;
  is_online: boolean;
}

export interface DiscoveredDevice {
  ip_address: string;
  name?: string;
  hostname?: string;
}

export interface SequenceStep {
  id?: number;
  device_id: number;
  device_name?: string;
  action: 'on' | 'off';
  delay_before: number;
  parallel_group?: number | null;
  order: number;
}

export interface Sequence {
  id: number;
  name: string;
  description?: string;
  steps: SequenceStep[];
}

export const devicesApi = {
  getAll: async (): Promise<Device[]> => {
    const res = await fetch(`${API_BASE}/devices`);
    return res.json();
  },

  get: async (id: number): Promise<Device> => {
    const res = await fetch(`${API_BASE}/devices/${id}`);
    return res.json();
  },

  discover: async (subnet?: string): Promise<DiscoveredDevice[]> => {
    const query = subnet ? `?subnet=${subnet}` : '';
    const res = await fetch(`${API_BASE}/devices/discover${query}`);
    return res.json();
  },

  create: async (data: { name: string; ip_address: string; role: string }): Promise<Device> => {
    const res = await fetch(`${API_BASE}/devices`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  update: async (id: number, data: { name?: string; ip_address?: string; role?: string }): Promise<Device> => {
    const res = await fetch(`${API_BASE}/devices/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  delete: async (id: number): Promise<void> => {
    await fetch(`${API_BASE}/devices/${id}`, { method: 'DELETE' });
  },

  toggle: async (id: number, state: boolean): Promise<Device> => {
    const res = await fetch(`${API_BASE}/devices/${id}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state }),
    });
    return res.json();
  },

  refresh: async (id: number): Promise<Device> => {
    const res = await fetch(`${API_BASE}/devices/${id}/refresh`, { method: 'POST' });
    return res.json();
  },

  allOn: async (): Promise<{ results: { device: string; success: boolean }[] }> => {
    const res = await fetch(`${API_BASE}/devices/all/on`, { method: 'POST' });
    return res.json();
  },

  allOff: async (): Promise<{ results: { device: string; success: boolean }[] }> => {
    const res = await fetch(`${API_BASE}/devices/all/off`, { method: 'POST' });
    return res.json();
  },
};

export const sequencesApi = {
  getAll: async (): Promise<Sequence[]> => {
    const res = await fetch(`${API_BASE}/sequences`);
    return res.json();
  },

  get: async (id: number): Promise<Sequence> => {
    const res = await fetch(`${API_BASE}/sequences/${id}`);
    return res.json();
  },

  create: async (data: { name: string; description?: string; steps: Omit<SequenceStep, 'id' | 'device_name'>[] }): Promise<Sequence> => {
    const res = await fetch(`${API_BASE}/sequences`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  update: async (id: number, data: { name?: string; description?: string; steps?: Omit<SequenceStep, 'id' | 'device_name'>[] }): Promise<Sequence> => {
    const res = await fetch(`${API_BASE}/sequences/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  delete: async (id: number): Promise<void> => {
    await fetch(`${API_BASE}/sequences/${id}`, { method: 'DELETE' });
  },

  execute: async (id: number): Promise<{ sequence: string; results: { step: number; device: string; action: string; success: boolean }[] }> => {
    const res = await fetch(`${API_BASE}/sequences/${id}/execute`, { method: 'POST' });
    return res.json();
  },
};

export type PlayOutcome = 'completed' | 'skipped' | 'stopped';

export interface SongStats {
  song_id: number;
  title: string;
  artist: string;
  completed: number;
  skipped: number;
  stopped: number;
  total: number;
}

export interface PlayerState {
  current_song: {
    id: number;
    title: string;
    artist: string;
  } | null;
  queue_length: number;
  queue_index: number;
  playlist_name: string | null;
  is_playing: boolean;
  current_time: number;
  duration: number;
  volume: number;
}

export const playerApi = {
  getState: async (): Promise<PlayerState> => {
    const res = await fetch(`${API_BASE}/player/state`);
    return res.json();
  },

  toggle: async (): Promise<void> => {
    await fetch(`${API_BASE}/player/toggle`, { method: 'POST' });
  },

  next: async (): Promise<void> => {
    await fetch(`${API_BASE}/player/next`, { method: 'POST' });
  },

  prev: async (): Promise<void> => {
    await fetch(`${API_BASE}/player/prev`, { method: 'POST' });
  },

  seek: async (time: number): Promise<void> => {
    await fetch(`${API_BASE}/player/seek`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ time }),
    });
  },

  setVolume: async (volume: number): Promise<void> => {
    await fetch(`${API_BASE}/player/volume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ volume }),
    });
  },

  stop: async (): Promise<void> => {
    await fetch(`${API_BASE}/player/stop`, { method: 'POST' });
  },
};

export const statsApi = {
  record: async (songId: number, outcome: PlayOutcome): Promise<void> => {
    await fetch(`${API_BASE}/stats/record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_id: songId, outcome }),
    });
  },

  getAllSongs: async (): Promise<SongStats[]> => {
    const res = await fetch(`${API_BASE}/stats/songs`);
    return res.json();
  },

  getSong: async (songId: number): Promise<SongStats> => {
    const res = await fetch(`${API_BASE}/stats/songs/${songId}`);
    return res.json();
  },

  getSummary: async (): Promise<{ total_plays: number; completed: number; skipped: number; stopped: number }> => {
    const res = await fetch(`${API_BASE}/stats/summary`);
    return res.json();
  },
};

// Button API — the same endpoint the StagePillar ESP32 calls
export interface PressResult {
  status: 'ok' | 'ignored';
  action: ButtonAction;
  reason?: string;
  show_state?: string;
}

export const buttonsApi = {
  /** With `side`, the press goes to the show director like a pillar's (docs/show-events-contract.md). */
  press: async (action: ButtonAction, side?: { side: 'L' | 'R'; firstPressAgoMs: number; taps?: number | null }): Promise<PressResult> => {
    const res = side
      ? await fetch(`${API_BASE}/buttons/press`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, side: side.side, first_press_ago_ms: side.firstPressAgoMs, taps: side.taps ?? undefined }),
        })
      : await fetch(`${API_BASE}/buttons/press/${action}`, { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
};

export type ShowLogLine = { t: string; mono: number; type: string; [field: string]: unknown };

export const showApi = {
  getSpec: async (): Promise<ShowSpec> => {
    const res = await fetch(`${API_BASE}/show/spec`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  getTunables: async (): Promise<Tunable[]> => {
    const res = await fetch(`${API_BASE}/show/tunables`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  setTunable: async (id: string, value: number | number[]): Promise<void> => {
    const res = await fetch(`${API_BASE}/show/tunables/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  },

  getSongMap: async (songId: number): Promise<SongMapInfo> => {
    const res = await fetch(`${API_BASE}/show/songmap/${songId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  getLog: async (limit = 30): Promise<ShowLogLine[]> => {
    const res = await fetch(`${API_BASE}/show/log?limit=${limit}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
};

// Pillar LED plans (docs/pillar-led-contract.md)
export type PillarSide = 'L' | 'R';

export interface PillarStatus {
  plans_version: number;
  preview_id: number;
  /** Only sides that have polled */
  pillars: Partial<Record<PillarSide, { seen_s_ago: number; running_version: number | null }>>;
  programs_version: number;
  /** What each side is commanded to play; program 0 = released */
  commands: Record<PillarSide, { seq: number; program: number }>;
  /** Tom's show director: anything but 'idle' means a game owns the LEDs */
  show_state: string;
}

export interface PillarProgram {
  id: number;
  name: string;
  sequence: PillarSequence;
  /** Compiled size in bytes */
  size: number;
}

/** A rejected save: a message per step index (-1 = whole sequence). */
export class PillarValidationError extends Error {
  stepErrors: Record<number, string>;

  constructor(stepErrors: Record<number, string>) {
    super(Object.values(stepErrors).join('; '));
    this.stepErrors = stepErrors;
  }
}

interface FastApiError {
  loc?: (string | number)[];
  msg?: string;
}

async function pillarRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/pillar${path}`, {
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  if (res.status === 422) {
    const body = await res.json();
    const stepErrors: Record<number, string> = {};
    // A plain message (e.g. a library limit) is about the whole sequence
    if (typeof body.detail === 'string') throw new PillarValidationError({ [-1]: body.detail });
    for (const e of (body.detail ?? []) as FastApiError[]) {
      const msg = (e.msg ?? 'Invalid').replace(/^Value error, /, '');
      const fromLoc = e.loc?.[1] === 'steps' && typeof e.loc[2] === 'number' ? e.loc[2] : undefined;
      const fromMsg = msg.match(/^Step (\d+):/);
      const index = fromLoc ?? (fromMsg ? Number(fromMsg[1]) - 1 : -1);
      stepErrors[index] = stepErrors[index] ?? msg.replace(/^Step \d+: /, '');
    }
    throw new PillarValidationError(stepErrors);
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export const pillarApi = {
  getPlans: () => pillarRequest<{ version: number; slots: Record<Slot, PillarSequence | null> }>('/plans'),
  getDefaults: () => pillarRequest<Record<Slot, PillarSequence>>('/plans/defaults'),
  save: (slot: Slot, seq: PillarSequence) =>
    pillarRequest<{ version: number }>(`/plans/${slot}`, { method: 'PUT', body: JSON.stringify(seq) }),
  reset: (slot: Slot) => pillarRequest<{ version: number }>(`/plans/${slot}`, { method: 'DELETE' }),
  startPreview: (seq: PillarSequence) =>
    pillarRequest<{ preview_id: number }>('/preview', { method: 'POST', body: JSON.stringify(seq) }),
  stopPreview: () => pillarRequest<{ preview_id: number }>('/preview', { method: 'DELETE' }),
  status: () => pillarRequest<PillarStatus>('/status'),
  listPrograms: () => pillarRequest<{ version: number; programs: PillarProgram[] }>('/programs'),
  createProgram: (name: string, sequence: PillarSequence) =>
    pillarRequest<{ id: number; version: number }>('/programs', { method: 'POST', body: JSON.stringify({ name, sequence }) }),
  updateProgram: (id: number, name: string, sequence: PillarSequence) =>
    pillarRequest<{ id: number; version: number }>(`/programs/${id}`, { method: 'PUT', body: JSON.stringify({ name, sequence }) }),
  deleteProgram: (id: number) => pillarRequest<{ version: number }>(`/programs/${id}`, { method: 'DELETE' }),
  /** Play a program on the given sides (0 = release) */
  command: (sides: PillarSide[], program: number) =>
    pillarRequest<{ seq: number; commands: PillarStatus['commands'] }>('/command', {
      method: 'POST', body: JSON.stringify({ sides, program }),
    }),
};
