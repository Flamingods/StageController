import { useEffect, useRef, useState } from 'react';
import { renderSequence } from '../../pillar/sequence';
import type { Sequence, Strip } from '../../pillar/types';
import type { PillarSide, PillarStatus } from '../../api';
import { StripCanvas } from './StripCanvas';

// The real strip runs with a global cap of 80/255 (FastLED brightness)
const PILLAR_CAP = 80 / 255;
const OFFLINE_AFTER_S = 5;
const SIDES: { side: PillarSide; name: string }[] = [
  { side: 'L', name: 'Left pillar' },
  { side: 'R', name: 'Right pillar' },
];

interface Props {
  sequence: Sequence;
  /** Shown while not playing (e.g. the selected step) */
  still: Strip;
  status: PillarStatus | null;
  pillarPlaying: boolean;
  onPlayOnPillar: () => void;
  onStopOnPillar: () => void;
  canPlay: boolean;
}

export function PillarPreview({ sequence, still, status, pillarPlaying, onPlayOnPillar, onStopOnPillar, canPlay }: Props) {
  const [playing, setPlaying] = useState(false);
  const [frame, setFrame] = useState<Strip>(still);
  const [trueBrightness, setTrueBrightness] = useState(true);
  const sequenceRef = useRef(sequence);
  useEffect(() => {
    sequenceRef.current = sequence;
  }, [sequence]);

  useEffect(() => {
    if (!playing) return;
    const start = performance.now();
    const seed = Math.floor(Math.random() * 0xffffffff);
    let raf = 0;
    const tick = () => {
      setFrame(renderSequence(sequenceRef.current, performance.now() - start, seed));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const sides = SIDES.map(({ side, name }) => {
    const p = status?.pillars[side];
    const online = p !== undefined && p.seen_s_ago < OFFLINE_AFTER_S;
    const label = online ? `online · v${p.running_version ?? '?'}` : p === undefined ? 'not seen' : 'offline';
    return { side, name, online, label };
  });
  const online = sides.some(s => s.online);

  return (
    <div className="pillar-preview">
      <div className="pillar-preview-label">Preview</div>
      <StripCanvas strip={playing ? frame : still} orientation="vertical" dim={trueBrightness ? PILLAR_CAP : 1} className="pillar-preview-strip" />
      <button type="button" className="pillar-btn" onClick={() => setPlaying(p => !p)} disabled={!canPlay && !playing}>
        {playing ? '■ Stop' : '▶ Preview'}
      </button>
      <label className="pillar-check" title="The real pillar runs at 80/255 brightness">
        <input type="checkbox" checked={trueBrightness} onChange={e => setTrueBrightness(e.target.checked)} />
        True brightness
      </label>

      <div className="pillar-preview-divider" />
      {sides.map(s => (
        <div key={s.side} className={`pillar-status ${s.online ? 'online' : 'offline'}`}>
          {s.name} {s.label}
        </div>
      ))}
      {pillarPlaying ? (
        <button type="button" className="pillar-btn" onClick={onStopOnPillar}>■ Stop pillar</button>
      ) : (
        <button
          type="button"
          className="pillar-btn"
          onClick={onPlayOnPillar}
          disabled={!canPlay}
          title={online ? 'Play this draft on both pillars' : 'No pillar has checked in recently; they may not respond'}
        >
          Play on pillar
        </button>
      )}
      {!online && <div className="pillar-hint">No pillar has checked in for {OFFLINE_AFTER_S}+ s</div>}
    </div>
  );
}
