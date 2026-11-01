import { useRef, useState } from 'react';
import { gradient, normalizeRange, paint, rampDelay, setPixelProps } from '../../pillar/painter';
import { EFFECTS, MAX_DURATION_MS, MIN_DURATION_MS, PIXEL_COUNT, hexToRgb } from '../../pillar/types';
import type { Direction, EffectName, EffectStep, FrameStep, Step, TransitionType } from '../../pillar/types';

/** `group` lets the page merge rapid edits (a brush stroke, a slider drag) into one undo step. */
export type StepChange = (step: Step, group?: string) => void;

interface Props {
  step: Step;
  error?: string;
  onChange: StepChange;
}

export function StepEditor({ step, error, onChange }: Props) {
  return (
    <div className="step-editor">
      {step.kind === 'effect'
        ? <EffectEditor step={step} onChange={onChange} />
        : <FrameEditor step={step} onChange={onChange} />}
      {error && <div className="step-editor-error">{error}</div>}
    </div>
  );
}

function DurationField({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <label className="pillar-field">
      <span>Duration (ms)</span>
      <input type="number" min={MIN_DURATION_MS} max={MAX_DURATION_MS} step={50} value={value}
        onChange={e => onChange(Number(e.target.value))} />
    </label>
  );
}

// ---- Effect steps -------------------------------------------------------------

const EFFECT_COLORS: Record<EffectName, { min: number; max: number }> = {
  off: { min: 0, max: 0 }, rainbow: { min: 0, max: 0 }, snake: { min: 0, max: 0 }, stripes: { min: 0, max: 0 },
  solid: { min: 1, max: 1 }, fill: { min: 1, max: 1 }, sparkle: { min: 1, max: 1 }, band: { min: 1, max: 1 },
  fade: { min: 2, max: 2 }, comet: { min: 1, max: 3 }, pulse: { min: 1, max: 3 },
};
const USES_DIRECTION: EffectName[] = ['rainbow', 'comet', 'fill', 'band', 'snake', 'stripes'];
const USES_BOUNCE: EffectName[] = ['comet', 'band'];
const USES_SPEED: EffectName[] = ['rainbow', 'comet', 'sparkle', 'pulse', 'band', 'snake', 'stripes'];
const DEFAULT_COLORS = ['#FF00C0', '#00E5FF', '#FFB000'];

function EffectEditor({ step, onChange }: { step: EffectStep; onChange: StepChange }) {
  const set = (patch: Partial<EffectStep>, group?: string) => onChange({ ...step, ...patch }, group);
  const range = EFFECT_COLORS[step.effect];

  const changeEffect = (effect: EffectName) => {
    const { min, max } = EFFECT_COLORS[effect];
    let colors = step.colors.slice(0, max);
    while (colors.length < min) colors = [...colors, DEFAULT_COLORS[colors.length]];
    const direction = !USES_BOUNCE.includes(effect) && step.direction === 'bounce' ? 'up' : step.direction;
    set({ effect, colors, direction });
  };

  return (
    <div className="effect-editor">
      <div className="pillar-fields">
        <label className="pillar-field">
          <span>Effect</span>
          <select value={step.effect} onChange={e => changeEffect(e.target.value as EffectName)}>
            {EFFECTS.map(name => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
        <DurationField value={step.duration_ms} onChange={v => set({ duration_ms: v }, 'duration')} />
        <label className="pillar-field">
          <span>Brightness {Math.round(step.brightness / 2.55)}%</span>
          <input type="range" min={0} max={255} value={step.brightness}
            onChange={e => set({ brightness: Number(e.target.value) }, 'brightness')} />
        </label>
        {USES_DIRECTION.includes(step.effect) && (
          <label className="pillar-field">
            <span>Direction</span>
            <select value={step.direction} onChange={e => set({ direction: e.target.value as Direction })}>
              <option value="up">Up</option>
              <option value="down">Down</option>
              {USES_BOUNCE.includes(step.effect) && <option value="bounce">Bounce</option>}
            </select>
          </label>
        )}
        {USES_SPEED.includes(step.effect) && (
          <label className="pillar-field">
            <span>Speed {step.speed.toFixed(2)}×</span>
            <input type="range" min={0.25} max={4} step={0.0625} value={step.speed}
              onChange={e => set({ speed: Number(e.target.value) }, 'speed')} />
          </label>
        )}
      </div>

      {range.max > 0 && (
        <div className="effect-colors">
          <span className="pillar-field-label">{range.max > 1 && range.min < range.max ? 'Colours (one per pass)' : 'Colours'}</span>
          {step.colors.map((c, i) => (
            <span key={i} className="effect-color">
              <input type="color" value={c.toLowerCase()}
                onChange={e => set({ colors: step.colors.map((x, j) => (j === i ? e.target.value.toUpperCase() : x)) }, `color-${i}`)} />
              {step.colors.length > range.min && (
                <button type="button" className="icon-btn" title="Remove colour"
                  onClick={() => set({ colors: step.colors.filter((_, j) => j !== i) })}>×</button>
              )}
            </span>
          ))}
          {step.colors.length < range.max && (
            <button type="button" className="pillar-btn small"
              onClick={() => set({ colors: [...step.colors, DEFAULT_COLORS[step.colors.length]] })}>+ Colour</button>
          )}
        </div>
      )}
    </div>
  );
}

// ---- Frame steps --------------------------------------------------------------

type Tool = 'paint' | 'fill' | 'gradient' | 'select' | 'eraser';
const TOOLS: { id: Tool; label: string; hint: string }[] = [
  { id: 'paint', label: 'Paint', hint: 'Click or drag to paint LEDs' },
  { id: 'fill', label: 'Fill', hint: 'Click to fill every LED' },
  { id: 'gradient', label: 'Gradient', hint: 'Drag from one LED to another: colour → second colour' },
  { id: 'select', label: 'Select', hint: 'Drag to select LEDs, then set brightness / fade / delay' },
  { id: 'eraser', label: 'Eraser', hint: 'Click or drag to turn LEDs off' },
];
const MAX_RECENT = 8;

function shown(color: string, brightness: number): string {
  const [r, g, b] = hexToRgb(color).map(c => Math.round((c * brightness) / 255));
  return `rgb(${r},${g},${b})`;
}

function FrameEditor({ step, onChange }: { step: FrameStep; onChange: StepChange }) {
  const [tool, setTool] = useState<Tool>('paint');
  const [color, setColor] = useState('#FF00C0');
  const [color2, setColor2] = useState('#00E5FF');
  const [recent, setRecent] = useState<string[]>(['#FFFFFF', '#FF0000', '#FFB000', '#00E5FF']);
  const [selection, setSelection] = useState<[number, number] | null>(null);
  const [fade, setFade] = useState(200);
  const [delayFrom, setDelayFrom] = useState(0);
  const [delayTo, setDelayTo] = useState(500);
  const stripRef = useRef<HTMLDivElement>(null);
  const stroke = useRef<{ base: FrameStep; anchor: number; touched: Set<number>; group: string } | null>(null);

  const set = (patch: Partial<FrameStep>, group?: string) => onChange({ ...step, ...patch }, group);

  const pickColor = (c: string) => {
    setColor(c);
    setRecent(r => [c, ...r.filter(x => x !== c)].slice(0, MAX_RECENT));
  };

  const ledAt = (clientX: number): number => {
    const rect = stripRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(PIXEL_COUNT - 1, Math.floor(((clientX - rect.left) / rect.width) * PIXEL_COUNT)));
  };

  const applyStroke = (index: number) => {
    const s = stroke.current;
    if (!s) return;
    if (tool === 'select') {
      setSelection(normalizeRange(s.anchor, index));
      return;
    }
    if (tool === 'gradient') {
      onChange(gradient(s.base, s.anchor, index, color, color2), s.group);
      return;
    }
    const [lo, hi] = normalizeRange(s.anchor, index);
    // Fill in skipped LEDs when the pointer moves fast
    for (let i = lo; i <= hi; i++) s.touched.add(i);
    s.anchor = index;
    onChange(paint(s.base, [...s.touched], tool === 'eraser' ? '#000000' : color), s.group);
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const index = ledAt(e.clientX);
    if (tool === 'fill') {
      onChange(paint(step, [...Array(PIXEL_COUNT).keys()], color));
      return;
    }
    e.currentTarget.setPointerCapture(e.pointerId);
    stroke.current = { base: step, anchor: index, touched: new Set(), group: `stroke-${Date.now()}` };
    if (tool === 'select') setSelection([index, index]);
    applyStroke(index);
    if (tool !== 'eraser' && tool !== 'select') pickColor(color);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (stroke.current) applyStroke(ledAt(e.clientX));
  };

  const endStroke = () => {
    stroke.current = null;
  };

  const selected = selection ? [...Array(selection[1] - selection[0] + 1).keys()].map(k => k + selection[0]) : [];
  const t = step.transition;

  return (
    <div className="frame-editor">
      <div className="frame-toolbar">
        {TOOLS.map(x => (
          <button key={x.id} type="button" title={x.hint}
            className={`tool-btn ${tool === x.id ? 'active' : ''}`} onClick={() => setTool(x.id)}>{x.label}</button>
        ))}
        <span className="toolbar-gap" />
        <label className="swatch-input" title="Colour">
          <input type="color" value={color.toLowerCase()} onChange={e => setColor(e.target.value.toUpperCase())} />
        </label>
        <label className="swatch-input secondary" title="Second colour (gradient end)">
          <input type="color" value={color2.toLowerCase()} onChange={e => setColor2(e.target.value.toUpperCase())} />
        </label>
        {recent.map(c => (
          <button key={c} type="button" className="swatch" style={{ background: c }} title={c} onClick={() => pickColor(c)} />
        ))}
      </div>

      <div
        ref={stripRef}
        className={`frame-strip tool-${tool}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endStroke}
        onPointerCancel={endStroke}
      >
        {step.pixels.map((px, i) => (
          <div key={i}
            className={`frame-led ${selection && i >= selection[0] && i <= selection[1] ? 'selected' : ''}`}
            style={{ background: shown(px.color, px.brightness) }}
            title={`LED ${i + 1}: ${px.color} · ${Math.round(px.brightness / 2.55)}%${t.type === 'custom' ? ` · delay ${px.delay_ms} · fade ${px.fade_ms}` : ''}`}
          />
        ))}
      </div>
      <div className="frame-strip-ends"><span>LED 1 (bottom)</span><span>LED 100 (top)</span></div>

      <div className="pillar-fields">
        <label className="pillar-field">
          <span>Transition</span>
          <select value={t.type} onChange={e => set({ transition: { ...t, type: e.target.value as TransitionType } })}>
            <option value="cut">Cut</option>
            <option value="crossfade">Crossfade</option>
            <option value="wipe">Wipe</option>
            <option value="custom">Custom (per LED)</option>
          </select>
        </label>
        {(t.type === 'crossfade' || t.type === 'wipe') && (
          <label className="pillar-field">
            <span>Transition time (ms)</span>
            <input type="number" min={0} max={step.duration_ms} step={50} value={t.ms}
              onChange={e => set({ transition: { ...t, ms: Number(e.target.value) } }, 'transition-ms')} />
          </label>
        )}
        {t.type === 'wipe' && (
          <label className="pillar-field">
            <span>Wipe direction</span>
            <select value={t.direction} onChange={e => set({ transition: { ...t, direction: e.target.value as 'up' | 'down' } })}>
              <option value="up">Up</option>
              <option value="down">Down</option>
            </select>
          </label>
        )}
        <DurationField value={step.duration_ms} onChange={v => set({ duration_ms: v }, 'duration')} />
      </div>

      <div className="selection-panel">
        {selection ? (
          <>
            <span className="pillar-field-label">
              LEDs {selection[0] + 1}–{selection[1] + 1}
              <button type="button" className="icon-btn" title="Clear selection" onClick={() => setSelection(null)}>×</button>
            </span>
            <label className="pillar-field">
              <span>Brightness {Math.round(step.pixels[selection[0]].brightness / 2.55)}%</span>
              <input type="range" min={0} max={255} value={step.pixels[selection[0]].brightness}
                onChange={e => onChange(setPixelProps(step, selected, { brightness: Number(e.target.value) }), 'sel-brightness')} />
            </label>
            <label className="pillar-field">
              <span>Fade (ms)</span>
              <span className="inline-apply">
                <input type="number" min={0} max={MAX_DURATION_MS} step={50} value={fade} onChange={e => setFade(Number(e.target.value))} />
                <button type="button" className="pillar-btn small" onClick={() => onChange(setPixelProps(step, selected, { fade_ms: fade }))}>Apply</button>
              </span>
            </label>
            <label className="pillar-field">
              <span>Delay (ms), ramp from → to</span>
              <span className="inline-apply">
                <input type="number" min={0} max={MAX_DURATION_MS} step={50} value={delayFrom} onChange={e => setDelayFrom(Number(e.target.value))} />
                <input type="number" min={0} max={MAX_DURATION_MS} step={50} value={delayTo} onChange={e => setDelayTo(Number(e.target.value))} />
                <button type="button" className="pillar-btn small"
                  onClick={() => onChange(rampDelay(step, selection[0], selection[1], delayFrom, delayTo))}>Apply</button>
              </span>
            </label>
            {t.type !== 'custom' && <span className="pillar-hint">Fade and delay switch the transition to Custom.</span>}
          </>
        ) : (
          <span className="pillar-hint">Use Select and drag across the strip to set brightness, fade or delay for a group of LEDs.</span>
        )}
      </div>
    </div>
  );
}
