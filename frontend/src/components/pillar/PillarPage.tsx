import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PillarValidationError, pillarApi } from '../../api';
import type { PillarProgram, PillarSide, PillarStatus } from '../../api';
import { newEffect, newFrame, validateSequence } from '../../pillar/painter';
import { sequenceDuration, stepStill } from '../../pillar/sequence';
import { MAX_STEPS, SLOTS, blankStrip } from '../../pillar/types';
import type { Sequence, Slot, Step } from '../../pillar/types';
import { PillarPreview } from './PillarPreview';
import { StepEditor } from './StepEditor';
import { StepList } from './StepList';
import './PillarPage.css';

const SLOT_INFO: Record<Slot, string> = {
  idle: 'Shown while no song is loaded',
  start: 'Plays for the whole song (single press starts the show)',
  claps: '2 taps, then back to the song loop',
  special: '3 or 5+ taps, then back to the song loop',
  skip: '4 taps, then back to the song loop',
  stop: 'Long press or show end, then idle',
};
const SIDE_NAMES: Record<PillarSide, string> = { L: 'Left', R: 'Right' };
const STATUS_POLL_MS = 2000;
const MAX_HISTORY = 100;
const GROUP_WINDOW_MS = 1500;
const NEW_PROGRAM = 'prog:new';

/** What the editor is working on: a slot name, `prog:<id>`, or `prog:new` (not saved yet). */
type Key = string;
const programKey = (id: number): Key => `prog:${id}`;
const programId = (key: Key): number | null => (key.startsWith('prog:') && key !== NEW_PROGRAM ? Number(key.slice(5)) : null);
const isProgram = (key: Key) => key.startsWith('prog:');

interface History {
  past: Sequence[];
  future: Sequence[];
  group?: string;
  groupAt?: number;
}

interface EditorState {
  defaults: Record<Slot, Sequence>;
  /** Last saved version; null = slot uses the ESP default, or a program not yet created */
  saved: Record<Key, Sequence | null>;
  drafts: Record<Key, Sequence>;
  names: Record<Key, string>;
  savedNames: Record<Key, string>;
  history: Record<Key, History>;
  selected: Record<Key, number>;
  programIds: number[];
  key: Key;
}

// Survives switching to another tab of the app (the page unmounts); a reload starts fresh
let cachedState: EditorState | null = null;

const clone = <T,>(v: T): T => structuredClone(v);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const emptyHistory = (): History => ({ past: [], future: [] });

function programEntries(programs: PillarProgram[]) {
  const entries = (make: (p: PillarProgram) => unknown) => Object.fromEntries(programs.map(p => [programKey(p.id), make(p)]));
  return {
    saved: entries(p => p.sequence) as Record<Key, Sequence>,
    drafts: entries(p => clone(p.sequence)) as Record<Key, Sequence>,
    names: entries(p => p.name) as Record<Key, string>,
    history: entries(() => emptyHistory()) as Record<Key, History>,
    selected: entries(() => 0) as Record<Key, number>,
  };
}

function isDirty(s: EditorState, key: Key): boolean {
  if (key === NEW_PROGRAM) return true;
  if (isProgram(key)) return !same(s.drafts[key], s.saved[key]) || s.names[key] !== s.savedNames[key];
  return !same(s.drafts[key], s.saved[key] ?? s.defaults[key as Slot]);
}

export function PillarPage() {
  const [state, setState] = useState<EditorState | null>(cachedState);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [serverErrors, setServerErrors] = useState<Record<number, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<PillarStatus | null>(null);
  const [previewId, setPreviewId] = useState(0);
  // When each side's current command was first seen, to estimate when a one-shot program ends
  const commandSeenAt = useRef<Record<PillarSide, { seq: number; at: number }>>({ L: { seq: -1, at: 0 }, R: { seq: -1, at: 0 } });
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    cachedState = state;
  }, [state]);

  useEffect(() => {
    if (cachedState) return;
    Promise.all([pillarApi.getPlans(), pillarApi.getDefaults(), pillarApi.listPrograms()])
      .then(([plans, defaults, library]) => {
        const progs = programEntries(library.programs);
        setState({
          defaults,
          saved: { ...plans.slots, ...progs.saved },
          drafts: { ...Object.fromEntries(SLOTS.map(s => [s, clone(plans.slots[s] ?? defaults[s])])), ...progs.drafts },
          names: { ...progs.names },
          savedNames: { ...progs.names },
          history: { ...Object.fromEntries(SLOTS.map(s => [s, emptyHistory()])), ...progs.history },
          selected: { ...Object.fromEntries(SLOTS.map(s => [s, 0])), ...progs.selected },
          programIds: library.programs.map(p => p.id),
          key: 'idle',
        });
      })
      .catch(e => setLoadError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    const poll = () => pillarApi.status()
      .then(st => {
        const t = Date.now();
        for (const side of ['L', 'R'] as PillarSide[]) {
          if (commandSeenAt.current[side].seq !== st.commands[side].seq) commandSeenAt.current[side] = { seq: st.commands[side].seq, at: t };
        }
        setStatus(st);
        setNow(t);
      })
      .catch(() => setStatus(null));
    poll();
    const id = window.setInterval(poll, STATUS_POLL_MS);
    return () => window.clearInterval(id);
  }, []);

  const dirtyKeys = useMemo(() => (state ? Object.keys(state.drafts).filter(k => isDirty(state, k)) : []), [state]);

  useEffect(() => {
    if (dirtyKeys.length === 0) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirtyKeys.length]);

  /** Replace the current draft; edits sharing a `group` within a moment form one undo step. */
  const updateDraft = useCallback((next: Sequence, group?: string, selected?: number) => {
    setServerErrors({});
    setMessage(null);
    setState(s => {
      if (!s) return s;
      const h = s.history[s.key];
      const t = Date.now();
      const merge = group !== undefined && h.group === group && t - (h.groupAt ?? 0) < GROUP_WINDOW_MS;
      const history: History = merge
        ? { ...h, groupAt: t }
        : { past: [...h.past, s.drafts[s.key]].slice(-MAX_HISTORY), future: [], group, groupAt: t };
      return {
        ...s,
        drafts: { ...s.drafts, [s.key]: next },
        history: { ...s.history, [s.key]: history },
        selected: selected === undefined ? s.selected : { ...s.selected, [s.key]: selected },
      };
    });
  }, []);

  const undoRedo = useCallback((redo: boolean) => {
    setState(s => {
      if (!s) return s;
      const h = s.history[s.key];
      const from = redo ? h.future : h.past;
      if (from.length === 0) return s;
      const target = from[from.length - 1];
      const current = s.drafts[s.key];
      const history: History = redo
        ? { past: [...h.past, current], future: h.future.slice(0, -1) }
        : { past: h.past.slice(0, -1), future: [...h.future, current] };
      const selected = Math.min(s.selected[s.key], Math.max(0, target.steps.length - 1));
      return {
        ...s,
        drafts: { ...s.drafts, [s.key]: target },
        history: { ...s.history, [s.key]: history },
        selected: { ...s.selected, [s.key]: selected },
      };
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'z') return;
      const target = e.target as HTMLElement;
      if (target.closest('input, textarea, select')) return;
      e.preventDefault();
      undoRedo(e.shiftKey);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [undoRedo]);

  const draft = state?.drafts[state.key];
  const clientErrors = useMemo(() => (draft ? validateSequence(draft) : {}), [draft]);
  const errors = Object.keys(serverErrors).length ? serverErrors : clientErrors;
  const hasErrors = Object.keys(clientErrors).length > 0;
  const selectedIndex = state ? Math.min(state.selected[state.key], Math.max(0, (draft?.steps.length ?? 1) - 1)) : 0;
  const selectedStep = draft?.steps[selectedIndex];
  const still = useMemo(() => (selectedStep ? stepStill(selectedStep) : blankStrip()), [selectedStep]);

  if (loadError) return <div className="pillar-page"><p className="pillar-error">Couldn't load pillar plans: {loadError}</p></div>;
  if (!state || !draft) return <div className="pillar-page"><p className="pillar-hint">Loading…</p></div>;

  const key = state.key;
  const program = isProgram(key);
  const id = programId(key);
  const history = state.history[key];
  const usesDefault = !program && state.saved[key] === null;
  const dirty = dirtyKeys.includes(key);
  const name = state.names[key] ?? '';

  const select = (k: Key) => {
    setServerErrors({});
    setMessage(null);
    setState({ ...state, key: k });
  };

  const setSteps = (steps: Step[], selected?: number, group?: string) => updateDraft({ ...draft, steps }, group, selected);

  const insertStep = (step: Step) => {
    const at = draft.steps.length ? selectedIndex + 1 : 0;
    setSteps([...draft.steps.slice(0, at), step, ...draft.steps.slice(at)], at);
  };

  const moveStep = (from: number, to: number) => {
    const steps = [...draft.steps];
    const [moved] = steps.splice(from, 1);
    steps.splice(to, 0, moved);
    setSteps(steps, to);
  };

  const fail = (what: string, e: unknown) => {
    if (e instanceof PillarValidationError) setServerErrors(e.stepErrors);
    else setMessage(`${what} failed: ${e instanceof Error ? e.message : e}`);
  };

  const newProgram = () => {
    setServerErrors({});
    setMessage(null);
    setState({
      ...state,
      key: NEW_PROGRAM,
      drafts: { ...state.drafts, [NEW_PROGRAM]: { loop: true, steps: [newEffect()] } },
      names: { ...state.names, [NEW_PROGRAM]: 'New program' },
      history: { ...state.history, [NEW_PROGRAM]: emptyHistory() },
      selected: { ...state.selected, [NEW_PROGRAM]: 0 },
      saved: { ...state.saved, [NEW_PROGRAM]: null },
    });
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      if (!program) {
        const { version } = await pillarApi.save(key as Slot, draft);
        setState(s => s && { ...s, saved: { ...s.saved, [key]: clone(draft) } });
        setMessage(`Saved · plans version ${version}. The pillars pick it up within a second.`);
      } else if (id === null) {
        const created = await pillarApi.createProgram(name.trim(), draft);
        const k = programKey(created.id);
        setState(s => {
          if (!s) return s;
          const without = <T,>(r: Record<Key, T>) => Object.fromEntries(Object.entries(r).filter(([x]) => x !== NEW_PROGRAM)) as Record<Key, T>;
          return {
            ...s,
            key: k,
            saved: { ...without(s.saved), [k]: clone(draft) },
            drafts: { ...without(s.drafts), [k]: draft },
            names: { ...without(s.names), [k]: name.trim() },
            savedNames: { ...s.savedNames, [k]: name.trim() },
            history: { ...without(s.history), [k]: s.history[NEW_PROGRAM] },
            selected: { ...without(s.selected), [k]: s.selected[NEW_PROGRAM] },
            programIds: [...s.programIds, created.id].sort((a, b) => a - b),
          };
        });
        setMessage(`Created program ${created.id} · library version ${created.version}`);
      } else {
        const { version } = await pillarApi.updateProgram(id, name.trim(), draft);
        setState(s => s && { ...s, saved: { ...s.saved, [key]: clone(draft) }, savedNames: { ...s.savedNames, [key]: name.trim() } });
        setMessage(`Saved · library version ${version}. Pillars playing it restart with the new version.`);
      }
    } catch (e) {
      fail('Save', e);
    } finally {
      setSaving(false);
    }
  };

  const resetToDefault = async () => {
    if (!window.confirm(`Reset "${key}" to the pillar's built-in sequence? Your saved version will be deleted.`)) return;
    try {
      const { version } = await pillarApi.reset(key as Slot);
      const def = clone(state.defaults[key as Slot]);
      setState(s => s && { ...s, saved: { ...s.saved, [key]: null } });
      updateDraft(def, undefined, 0);
      setMessage(`Reset to default · plans version ${version}`);
    } catch (e) {
      fail('Reset', e);
    }
  };

  const deleteProgram = async () => {
    if (id !== null && !window.confirm(`Delete program "${state.savedNames[key]}"? Pillars playing it are released.`)) return;
    try {
      if (id !== null) await pillarApi.deleteProgram(id);
      setState(s => {
        if (!s) return s;
        const without = <T,>(r: Record<Key, T>) => Object.fromEntries(Object.entries(r).filter(([x]) => x !== key)) as Record<Key, T>;
        return {
          ...s,
          key: 'idle',
          saved: without(s.saved), drafts: without(s.drafts), names: without(s.names), savedNames: without(s.savedNames),
          history: without(s.history), selected: without(s.selected),
          programIds: s.programIds.filter(p => p !== id),
        };
      });
      setMessage(id !== null ? 'Program deleted' : null);
    } catch (e) {
      fail('Delete', e);
    }
  };

  const sendCommand = async (sides: PillarSide[], prog: number) => {
    try {
      await pillarApi.command(sides, prog);
      const st = await pillarApi.status();
      setStatus(st);
    } catch (e) {
      fail(prog ? 'Play' : 'Release', e);
    }
  };

  const playOnPillar = async () => {
    try {
      const { preview_id } = await pillarApi.startPreview(draft);
      setPreviewId(preview_id);
    } catch (e) {
      fail('Pillar preview', e);
    }
  };

  const stopOnPillar = async () => {
    await pillarApi.stopPreview().catch(() => undefined);
    setPreviewId(0);
  };

  const sideStatus = (side: PillarSide): string => {
    const c = status?.commands[side];
    if (!c || c.program === 0) return 'normal (no program)';
    const progName = state.savedNames[programKey(c.program)] ?? `program ${c.program}`;
    if (status && status.show_state !== 'idle') return `${progName} · waiting — game running`;
    const seq = state.saved[programKey(c.program)];
    const seen = commandSeenAt.current[side];
    if (seq && !seq.loop && seen.seq === c.seq && now - seen.at > sequenceDuration(seq)) return `${progName} · finished (estimated)`;
    return `${progName} · playing`;
  };

  const pillarPlaying = previewId > 0 && status?.preview_id === previewId;
  const seconds = (sequenceDuration(draft) / 1000).toFixed(1);
  const label = program ? (name || 'Untitled program') : key;
  const info = program ? (id === null ? 'Not saved yet' : `Program ${id}`) : SLOT_INFO[key as Slot];

  return (
    <div className="pillar-page">
      <div className="pillar-header">
        <h2>Pillar LEDs</h2>
        <div className="slot-tabs">
          {SLOTS.map(s => (
            <button key={s} type="button" title={SLOT_INFO[s]}
              className={`slot-tab ${s === key ? 'active' : ''}`} onClick={() => select(s)}>
              {s}{state.drafts[s].loop ? ' ↻' : ''}
              {state.saved[s] === null && <span className="slot-dot" title="Uses the built-in default" />}
              {dirtyKeys.includes(s) && <span className="slot-dirty" title="Unsaved changes">•</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="program-tabs">
        <span className="pillar-field-label">Programs</span>
        {state.programIds.map(pid => {
          const k = programKey(pid);
          return (
            <button key={k} type="button" className={`slot-tab program-tab ${k === key ? 'active' : ''}`} onClick={() => select(k)}>
              {state.names[k]}{state.drafts[k].loop ? ' ↻' : ''}
              {dirtyKeys.includes(k) && <span className="slot-dirty" title="Unsaved changes">•</span>}
            </button>
          );
        })}
        {key === NEW_PROGRAM && <button type="button" className="slot-tab program-tab active">{name || 'New program'} •</button>}
        <button type="button" className="pillar-btn small" onClick={newProgram} disabled={key === NEW_PROGRAM}>+ New program</button>
      </div>

      <div className="pillar-layout">
        <div className="pillar-main">
          <section className="pillar-card">
            <div className="sequence-bar">
              {program && (
                <input className="program-name" value={name} maxLength={60} placeholder="Program name"
                  onChange={e => setState({ ...state, names: { ...state.names, [key]: e.target.value } })} />
              )}
              <span className="pillar-field-label">
                {!program && `${label} · `}{info} · {draft.steps.length} step{draft.steps.length === 1 ? '' : 's'} · {seconds} s
                {usesDefault && ' · built-in default'}
              </span>
              <label className="pillar-check">
                <input type="checkbox" checked={draft.loop} onChange={e => updateDraft({ ...draft, loop: e.target.checked })} />
                Loop
              </label>
            </div>

            <StepList steps={draft.steps} selected={selectedIndex} errors={errors}
              onSelect={i => setState({ ...state, selected: { ...state.selected, [key]: i } })}
              onMove={moveStep} />
            {errors[-1] && <div className="step-editor-error">{errors[-1]}</div>}

            <div className="sequence-actions">
              <button type="button" className="pillar-btn" disabled={draft.steps.length >= MAX_STEPS} onClick={() => insertStep(newEffect())}>+ Effect</button>
              <button type="button" className="pillar-btn" disabled={draft.steps.length >= MAX_STEPS} onClick={() => insertStep(newFrame())}>+ Frame</button>
              <button type="button" className="pillar-btn" disabled={!selectedStep || draft.steps.length >= MAX_STEPS}
                onClick={() => selectedStep && insertStep(clone(selectedStep))}>Duplicate</button>
              <button type="button" className="pillar-btn" disabled={!selectedStep}
                onClick={() => setSteps(draft.steps.filter((_, i) => i !== selectedIndex), Math.max(0, selectedIndex - 1))}>Delete</button>
              <span className="toolbar-gap" />
              <button type="button" className="pillar-btn" disabled={!history.past.length} onClick={() => undoRedo(false)} title="Undo (⌘Z)">↶ Undo</button>
              <button type="button" className="pillar-btn" disabled={!history.future.length} onClick={() => undoRedo(true)} title="Redo (⇧⌘Z)">↷ Redo</button>
            </div>
          </section>

          {selectedStep && (
            <section className="pillar-card">
              <div className="pillar-field-label">Step {selectedIndex + 1}</div>
              <StepEditor step={selectedStep} error={errors[selectedIndex]}
                onChange={(step, group) => setSteps(draft.steps.map((s, i) => (i === selectedIndex ? step : s)), undefined, group)} />
            </section>
          )}

          {program && (
            <section className="pillar-card program-play">
              <div className="pillar-field-label">Play on pillars</div>
              <div className="sequence-actions">
                <button type="button" className="pillar-btn" disabled={id === null || dirty} onClick={() => id && sendCommand(['L'], id)}>Left</button>
                <button type="button" className="pillar-btn" disabled={id === null || dirty} onClick={() => id && sendCommand(['R'], id)}>Right</button>
                <button type="button" className="pillar-btn primary" disabled={id === null || dirty} onClick={() => id && sendCommand(['L', 'R'], id)}>Both</button>
                {(id === null || dirty) && <span className="pillar-hint">Save first: the pillars play the saved version.</span>}
              </div>
              <ul className="side-status">
                {(['L', 'R'] as PillarSide[]).map(side => (
                  <li key={side}>
                    <b>{SIDE_NAMES[side]}:</b> {sideStatus(side)}
                    {status?.commands[side].program !== 0 && (
                      <button type="button" className="pillar-btn small" onClick={() => sendCommand([side], 0)}>Release</button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="pillar-save-bar">
            {message && <span className="pillar-message">{message}</span>}
            <span className="toolbar-gap" />
            {program ? (
              <button type="button" className="pillar-btn" onClick={deleteProgram}>{id === null ? 'Discard' : 'Delete program'}</button>
            ) : (
              <button type="button" className="pillar-btn" disabled={usesDefault && !dirty} onClick={resetToDefault}>Reset to default</button>
            )}
            <button type="button" className="pillar-btn primary" disabled={!dirty || hasErrors || saving || (program && !name.trim())} onClick={save}>
              {saving ? 'Saving…' : id === null && program ? 'Create program' : dirty ? 'Save' : 'Saved'}
            </button>
          </div>
        </div>

        <PillarPreview sequence={draft} still={still} status={status} pillarPlaying={pillarPlaying}
          onPlayOnPillar={playOnPillar} onStopOnPillar={stopOnPillar} canPlay={!hasErrors && draft.steps.length > 0} />
      </div>
    </div>
  );
}
