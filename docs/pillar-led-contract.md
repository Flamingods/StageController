# Pillar LED contract (StageController ⇄ StagePillar ESP32)

Version 2 — 2026-10-17 (v1 2026-10-02). Shared by both repos; StagePillar's spec links here.
Tom's `docs/show-events-contract.md` owns the show director, games and show events; this file
covers what the pillars download and how they combine it with show events (§9–§12).
Ownership: StagePillar owns the effect catalogue and its maths; StageController owns
the sequence format, the compiler and the HTTP endpoints. Change this file first.

## 1. Show state and pillar identity

- Two identical pillars, identified by **side**: `"L"` or `"R"` (left/right as seen from the
  entrance, as in the show-events contract). Same plans, same gestures; the side only selects
  show-event poles and program commands, and labels status and logs.
- **Show running** ⇔ `GET /api/player/state` → `current_song != null`. A paused song counts
  as running. Do not use `is_playing`.
- Presses: the pillar sends **every** gesture side-aware (`POST /api/buttons/press`, body in
  §9); the show director decides. There is no idle gate on the ESP any more. The legacy no-side
  path (`/press/{action}`) keeps the server idle gate: while idle only `start` and `stop` take
  effect, others reply `200 {"status":"ignored","reason":"show_stopped"}`.

## 2. Slots and playback

Slots: `idle`, `start`, `claps`, `special`, `skip`, `stop`. Gestures: 1 tap → start,
2 → claps, 3 and 5+ → special, 4 → skip, long press → stop.

- Show not running → `idle` (loops).
- Show running → `start`, looping for the whole song (also when music was started from the app).
- `claps` / `special` / `skip` → play that slot, then return to `start` if the show is still
  running, otherwise `idle`.
- `stop`, or the show ends → `stop` once, then `idle`.
- `loop=1`: repeat until the next gesture or state change; `loop=0`: play once.
- A gesture always interrupts what is playing, including a preview.
- Missing slot (HTTP 404) → the ESP's code default (section 6).

## 3. Sequence JSON (editor/server format)

```json
{
  "loop": false,
  "steps": [
    {"kind": "effect", "effect": "comet", "duration_ms": 2100, "brightness": 255,
     "direction": "bounce", "speed": 1.5, "colors": ["#FF00C0", "#00E5FF", "#FFB000"]},
    {"kind": "frame", "duration_ms": 800,
     "transition": {"type": "wipe", "ms": 400, "direction": "up"},
     "pixels": [{"color": "#FFB000", "brightness": 255, "fade_ms": 0, "delay_ms": 0}, "… 100 entries, index 0 = bottom"]}
  ]
}
```

- `effect`: `off|solid|rainbow|comet|fill|sparkle|pulse|band|fade|snake|stripes`.
- `direction`: `up|down|bounce` (bounce is meaningful for comet and band; others treat it as up).
- `speed`: 0.25–4.0 (1.0 = reference speed); stored on the wire as `round(speed*16)`.
- `colors`: 0–3 `#RRGGBB` strings.
- `transition.type`: `cut | crossfade | wipe | custom`. `ms` is used by crossfade and wipe;
  `direction` (`up|down`) by wipe. Per-pixel `fade_ms`/`delay_ms` are used **only** by `custom`.
- `brightness` (effect and pixel): 0–255.

**Validation** (server rejects with HTTP 422, the ESP falls back to the slot default):
1–64 steps; `duration_ms` 50–60000; frames have exactly 100 pixels; crossfade/wipe
`ms ≤ duration_ms`; for `custom` frames, every pixel's `delay_ms + fade_ms ≤ duration_ms`;
speed 0.25–4.0; known effect/direction/transition; ≤ 3 colours; compiled file ≤ 48 KB.

## 4. Baking (server, before sending)

The ESP knows one frame rule: **at the instant a frame step starts, take a snapshot of what
the strip shows (the previous step's output, whatever played before this sequence, or on a
loop restart the last step's final output). Each pixel holds its snapshot colour until
`delay_ms`, then fades linearly from that fixed snapshot to its target over `fade_ms`;
pixels still transitioning when the step ends snap to their target.** The server converts
every transition into it:

| type | delay_ms for pixel i (0..99) | fade_ms |
|---|---|---|
| cut | 0 | 0 |
| crossfade | 0 | `ms` |
| wipe up | `i * ms / 100` | `min(150, ms / 10)` |
| wipe down | `(99 - i) * ms / 100` | `min(150, ms / 10)` |
| custom | pixel `delay_ms` | pixel `fade_ms` |

(integer division). For cut/crossfade/wipe the server then trims each pixel to fit the step:
`fade_ms = min(fade_ms, duration_ms − delay_ms)`. Brightness is baked into colour:
`c * brightness / 255` per channel.

## 5. Binary format v1 (`PLP1`), little-endian

Header, 16 bytes:

| offset | size | field |
|---|---|---|
| 0 | 4 | magic `"PLP1"` |
| 4 | 4 | `plans_version` u32 (preview files: the preview id) |
| 8 | 1 | `loop` u8 (0/1) |
| 9 | 1 | `step_count` u8 (1..64) |
| 10 | 2 | reserved u16 = 0 |
| 12 | 4 | `crc32` u32 = `zlib.crc32` of every byte after the header (check: `"123456789"` → `0xCBF43926`) |

Steps follow back to back, each starting with `kind` u8:

- **EFFECT** (kind 1, 16 bytes): kind u8 | effect u8 | duration_ms u16 | brightness u8 |
  direction u8 (0 up, 1 down, 2 bounce) | speed_x16 u8 (4..64) | colors 3×[r,g,b] (unused = 0).
- **FRAME** (kind 2, 703 bytes): kind u8 | duration_ms u16 | 100 × [r u8, g u8, b u8,
  fade_ms u16, delay_ms u16].

Effect ids: 0 off, 1 solid, 2 rainbow, 3 comet, 4 fill, 5 sparkle, 6 pulse, 7 band, 8 fade, 9 snake, 10 stripes.

A golden vector lives at `backend/tests/fixtures/pillar_golden.json` → `pillar_golden.bin`;
StagePillar copies the `.bin` as a fixture and parses it in its native tests.

## 6. Defaults (ESP code = truth; server serves them verbatim)

| slot | loop | step |
|---|---|---|
| idle | 1 | stripes, 20480 ms, 255, up, speed 1.0 |
| start | 1 | comet, 2100 ms, 255, bounce, speed 1.5, `#FF00C0 #00E5FF #FFB000` |
| claps | 0 | sparkle, 1200 ms, 255, up, 1.0, `#FFFFFF` |
| special | 0 | pulse, 1500 ms, 255, up, 1.0, `#0000FF #8000FF #FF00C0` |
| skip | 0 | band, 500 ms, 255, up, 1.0, `#00FFFF` |
| stop | 0 | fade, 1500 ms, 255, up, 1.0, `#FF0000 #280000` |

## 7. HTTP

ESP-facing:
- `GET /api/player/state` adds `pillar_plans_version` (u32, bumped on every save/reset),
  `pillar_preview_id` (0 = none), `pillar_programs_version` (§10), `show_palette_version` (§11)
  and, for the polling side, `pillar_command` (§10). The ESP polls it every 1 s with query
  `?client=pillar&side=L|R&running_version=<n>`; the server keeps status per side. No `side` =
  `R` (the board flashed before two pillars); any other value → 422.
- `GET /api/pillar/plans/{slot}.bin` → `application/octet-stream`, or 404 when the slot uses
  the default (ESP deletes its copy). On a version change the ESP fetches all six slots to temp
  files and renames on success; if a file's header version differs from the version it began
  fetching for, it restarts the round.
- `GET /api/pillar/preview.bin` → the current preview, or 404.

Preview: a new non-zero `pillar_preview_id` → fetch `preview.bin` (stored as `/preview.bin`,
never as a slot) and play it immediately; id back to 0, or a non-loop preview finishing → normal
behaviour. Ids expire after 60 s.

App-facing: `GET /api/pillar/plans`, `GET /api/pillar/plans/defaults`,
`PUT|DELETE /api/pillar/plans/{slot}`, `POST|DELETE /api/pillar/preview`,
`GET /api/pillar/status` → `{"plans_version","preview_id","pillars":{"L"|"R":{"seen_s_ago",
"running_version"}}}` (only sides that have polled), plus the programs endpoints in §10.
"Play on pillar" (preview) plays on both pillars.

## 8. Effect maths (integer, uint32, truncating division; N = 100; index 0 = bottom)

Implemented in StagePillar `lib/pillar/led_catalogue.cpp` (commit dc0524b) and mirrored in the
app's preview. `t` = ms since step start, clamped to duration−1.

- `scaled(refMs) = max(1, refMs*16/speed_x16)`; `colorCount` = leading non-black colours, min 1;
  `passUp(dir, pass)`: down → false, bounce → pass even, up → true.
- Brightness < 255: every channel `c*brightness/255`, applied last. `scale(c, level) = c*level/255`.
- `hueToRgb(h)`: region = h/43; rise = (h − region·43)·6 (u8 wrap); fall = 255 − rise;
  regions 0..5 → (255,rise,0), (fall,255,0), (0,255,rise), (0,fall,255), (rise,0,255), (255,0,fall).
- off: black. solid: colors[0].
- rainbow: shift = t/scaled(80); hue = u8((up ? i − shift : i + shift)·5) (down only if dir = down).
- comet: passMs = scaled(1000); pass = t/passMs; head = (t%passMs)·(N+20)/passMs; colour =
  colors[pass % colorCount]; pos = passUp ? i : N−1−i; lit if pos ≤ head and head−pos < 20,
  level = 255·(20−(head−pos))/20.
- fill: fillMs = duration·3/5; head = t < fillMs ? t·N/fillMs : N; level = t < fillMs ? 255 :
  255·(duration−t)/(duration−fillMs); pos = down ? N−1−i : i; lit if pos < head.
- sparkle: colour = colors[0] or white; level = 255·(duration−t)/duration; window = t/scaled(80);
  lit if hash(i, seed, window) % 100 < 15 with hash: x = a·2654435761 ^ b·40503 ^ c·2246822519;
  x ^= x>>15; x ·= 2654435761; x ^= x>>13 (u32). Seed = millis() at sequence start.
- pulse: period = scaled(750); phase = t%period; half = period/2; level = phase < half ?
  phase·255/half : (period−phase)·255/half; colour = colors[(t/period) % colorCount].
- band: passMs = scaled(500); pass = t/passMs; head = (t%passMs)·(N+15)/passMs; pos as comet;
  lit with colors[0] if pos ≤ head and pos+15 > head.
- fade: per channel a + (b−a)·t/duration (signed), a = colors[0], b = colors[1].
- snake: a 36-LED rainbow snake climbs the pillar (bottom to top, or top to bottom for dir = down) once
  per pass of scaled(3000) ms, leaving sparkles that fade over scaled(1500) ms; the rest of the
  pillar is dark. Colours are ignored. See StagePillar `renderSnake` for the exact maths.
- stripes: the rainbow flowing along the pillar (80 ms per LED at speed 1.0) cut into 32-LED periods:
  20 lit LEDs with 3-LED soft ends, then 12 dark. Colours are ignored. See StagePillar `renderStripes`.
- Sequence: steps back to back, no blending; loop → t %= total.
- The strip has a global cap of 80/255 (FastLED brightness) on top of everything.

Porting pitfalls (TypeScript preview):
- sparkle hash: use `Math.imul(...)` and `>>> 0` after every step; plain JS multiplication
  loses precision past 2^53.
- fade: C integer division truncates toward zero, so use `Math.trunc`, not `Math.floor`, when b < a.
- rainbow: `((i − shift)·5) & 0xFF` matches the C uint32 wrap.

## 9. Show alignment (with docs/show-events-contract.md)

Press: `POST /api/buttons/press` with `{"action","side":"L"|"R","taps":<real count>,
"first_press_ago_ms":<ms from the gesture's first debounced press to the send>}`; `taps` is the
real count (no cap at 5). The ESP listens to `/api/buttons/ws` for show events and commands.

**Layers, top wins:** preview > show event (show state not `idle`) > gesture one-shot (only in
show state `idle`) > program (§10) > slot base (idle loop, or the start loop while running).
A gesture ends a running preview (§2) even during a game; the gesture's one-shot is still only
drawn in show state `idle`.
In show state `idle` the poles say `off` and the ESP draws its own layers below.

No button rings: the pillar is the button, so the ESP ignores `buttons` in show events and draws
its pole on the pillar strip.

## 10. Programs (commanded by the Pi, per side)

- A library of up to **24** programs, ids 1..255, each a sequence (§3) compiled to PLP1 (§5);
  ≤ 48 KB / 64 steps each, ≤ 512 KB in total (server 422 otherwise; the ESP stages a whole new
  library next to the active one in its 1.4 MB partition). Both pillars download all of it.
- `pillar_programs_version` in the state reply; when it changes the ESP fetches
  `GET /api/pillar/programs/index` → `{"version":N,"ids":[1,4,7]}` then
  `GET /api/pillar/programs/<id>.bin`; the header's `plans_version` field carries the programs
  version, and a mid-round mismatch restarts the round (as for slots).
- **Command** per side: `{"seq":S,"program":P}`, P = 0 → release. `seq` is a server counter that
  never decreases (persisted); the ESP applies only `seq` > the last one it applied.
  - Fast path: a WebSocket message on `/api/buttons/ws`
    `{"action":"pillar_command","side":"L"|"R","seq":S,"program":P}`, broadcast to all; each ESP
    keeps its own side.
  - Backup: the state reply for `?side=X` carries `"pillar_command":{"seq":S,"program":P}`, so a
    missed message or a reboot is fixed within ~1 s.
- The ESP keeps the latest command even when the id is unknown or not yet downloaded ("unknown"
  = normal behaviour for now); after every library sync it re-resolves the command, and restarts
  the active program if its file changed.
- An active program replaces the slot base layer. Gestures play their slot one-shot, then return
  to the program. A non-loop program that finishes → normal behaviour.
- Release (program 0) → normal behaviour; the command is cleared.
- No successful poll for 10 s → the program **pauses**: normal behaviour, the command is kept,
  and the program resumes when polls succeed again (unless a newer command released it).
- During a game (show state not `idle`) show events own the LEDs; the stored command waits below
  and resumes after the game. The server does not drop commands sent during a game.

## 11. Palette and pole rendering (matches Tom's emulator, frontend/src/show)

- `GET /api/show/palette` → `{"version":N,"colors":{"<name>":{"ramp":[[r,g,b],[r,g,b],[r,g,b]],
  "gain":G,"drift_ms":P}}}`; `show_palette_version` in the state reply changes whenever a ramp or
  a colour tunable changes. `ramp` = [dim, base, bright]; `gain` = tunable `<name>Gain` (1.0 when
  absent); `drift_ms` = `pinkDriftPeriodMs` for pink, else `driftPeriodMs`. Unknown colour name →
  white.
- Drift, on **every** colour including white: for LED i at time t (s), period = drift_ms/1000,
  k = 0.5 + 0.5·sin(0.33·i − 2π·t/period); colour = lerp(ramp[0], ramp[1], 2k) when k < 0.5, else
  lerp(ramp[1], ramp[2], 2k − 1); then × gain, capped at 255.
- Pole: lit LEDs (from the bottom) = round(pct/100 · 100). `glow` = all 100 at `level` %
  (ambientGlowPct, default 35). `solid` = fill at pct. `pulse` = fill at pct with brightness
  0.1 + 0.9·(0.5 − 0.5·cos(2π·elapsed/period)), period = `ms` or 500 ms. `blink` = 250 ms on /
  250 ms off. `drain` = pct·max(0, 1 − elapsed/ms) from receipt. `off` = dark.



## 12. Show poles driven by the hub (added 2026-10-17)

The Pi draws each pillar's pole (docs/show-events-contract.md) through the **preview** of section 7,
so the firmware needs no show-event code. `app/features/pillar/poles.py` owns it.

- Pillar 1 is always **R**, pillar 2 always **L** (as seen from the entrance).
- Press: `POST /api/buttons/press/<action>?pillar_id=N` goes to the show director as a side-aware
  press of that side; the tap count is the one the action stands for (4 = skip, 5+ = special).
  Without `pillar_id` the legacy path is unchanged.
- Every show event turns that side's pole into a looping sequence: `solid` = a frame lit to `pct`;
  `glow` = the whole strip at `level`; `pulse`/`blink` = the `pulse` effect at the event's `ms`;
  `drain` = a custom frame falling from the top over `ms`; thunder's rising pole = one custom frame
  that climbs from `pct` to the top over the rest of `cooldownMs` (the ESP runs the rise, so the
  per-percent events do not restart it). A new preview id is issued only when the look changes,
  and again after each press from that pillar (a gesture ends a preview on the ESP).
- Poll `?client=pillar&pillar_id=N`: `pillar_preview_id` is the editor's draft when one plays,
  else that pillar's pole id; `idle` sets it to 0 and the pillar falls back to its slots.
- `GET /api/pillar/preview.bin` has no pillar id: the Pi serves the pole of the pillar that last
  polled from the caller's address. Show previews do not expire.
- Latency: a pole change reaches the strip within one poll (~1 s).
