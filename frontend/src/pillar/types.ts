// Pillar LED sequence format — mirrors backend/app/features/pillar/schemas.py
// and docs/pillar-led-contract.md §3.

export const PIXEL_COUNT = 100;
export const MAX_STEPS = 64;
export const MIN_DURATION_MS = 50;
export const MAX_DURATION_MS = 60000;

export const SLOTS = ['idle', 'start', 'claps', 'special', 'skip', 'stop'] as const;
export type Slot = (typeof SLOTS)[number];

export const EFFECTS = ['off', 'solid', 'rainbow', 'comet', 'fill', 'sparkle', 'pulse', 'band', 'fade', 'snake', 'stripes'] as const;
export type EffectName = (typeof EFFECTS)[number];
export type Direction = 'up' | 'down' | 'bounce';

export interface EffectStep {
  kind: 'effect';
  effect: EffectName;
  duration_ms: number;
  brightness: number;
  direction: Direction;
  speed: number;
  colors: string[];
}

export interface Pixel {
  color: string;
  brightness: number;
  fade_ms: number;
  delay_ms: number;
}

export type TransitionType = 'cut' | 'crossfade' | 'wipe' | 'custom';

export interface Transition {
  type: TransitionType;
  ms: number;
  direction: 'up' | 'down';
}

export interface FrameStep {
  kind: 'frame';
  duration_ms: number;
  transition: Transition;
  pixels: Pixel[];
}

export type Step = EffectStep | FrameStep;

export interface Sequence {
  loop: boolean;
  steps: Step[];
}

/** One rendered strip: PIXEL_COUNT × [r, g, b], index 0 = bottom. */
export type Strip = Uint8Array;

export function blankStrip(): Strip {
  return new Uint8Array(PIXEL_COUNT * 3);
}

export function hexToRgb(hex: string): [number, number, number] {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
}

export function rgbToHex(r: number, g: number, b: number): string {
  return '#' + [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('').toUpperCase();
}

/** Wire speed encoding (contract §5): round(speed * 16), clamped to 4..64. */
export function speedX16(speed: number): number {
  return Math.max(4, Math.min(64, Math.round(speed * 16)));
}
