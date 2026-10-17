# Pillar LED contract (StageController ⇄ StagePillar ESP32)

Version 1 — 2026-10-02. Shared by both repos; StagePillar's spec links here.
Ownership: StagePillar owns the effect catalogue and its maths; StageController owns
the sequence format, the compiler and the HTTP endpoints. Change this file first.

## 1. Show state

- **Show running** ⇔ `GET /api/player/state` → `current_song != null`. A paused song counts
  as running. Do not use `is_playing`.
- While idle, only `start` (single press) and `stop` (long press) take effect; the server
  replies `200 {"status":"ignored","reason":"show_stopped"}` to the others.

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

- `effect`: `off|solid|rainbow|comet|fill|sparkle|pulse|band|fade`.
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

Effect ids: 0 off, 1 solid, 2 rainbow, 3 comet, 4 fill, 5 sparkle, 6 pulse, 7 band, 8 fade.

A golden vector lives at `backend/tests/fixtures/pillar_golden.json` → `pillar_golden.bin`;
StagePillar copies the `.bin` as a fixture and parses it in its native tests.

## 6. Defaults (ESP code = truth; server serves them verbatim)

| slot | loop | step |
|---|---|---|
| idle | 1 | rainbow, 20480 ms, 255, up, speed 1.0 |
| start | 1 | comet, 2100 ms, 255, bounce, speed 1.5, `#FF00C0 #00E5FF #FFB000` |
| claps | 0 | sparkle, 1200 ms, 255, up, 1.0, `#FFFFFF` |
| special | 0 | pulse, 1500 ms, 255, up, 1.0, `#0000FF #8000FF #FF00C0` |
| skip | 0 | band, 500 ms, 255, up, 1.0, `#00FFFF` |
| stop | 0 | fade, 1500 ms, 255, up, 1.0, `#FF0000 #280000` |

## 7. HTTP

ESP-facing:
- `GET /api/player/state` adds `pillar_plans_version` (u32, bumped on every save/reset) and
  `pillar_preview_id` (0 = none). The ESP polls it every 1 s with query
  `?client=pillar&running_version=<n>` so the server can show pillar status.
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
`GET /api/pillar/status`.

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
- Sequence: steps back to back, no blending; loop → t %= total.
- The strip has a global cap of 80/255 (FastLED brightness) on top of everything.

Porting pitfalls (TypeScript preview):
- sparkle hash: use `Math.imul(...)` and `>>> 0` after every step; plain JS multiplication
  loses precision past 2^53.
- fade: C integer division truncates toward zero, so use `Math.trunc`, not `Math.floor`, when b < a.
- rainbow: `((i − shift)·5) & 0xFF` matches the C uint32 wrap.

## 9. Show poles driven by the hub (added 2026-10-17)

The Pi draws each pillar's pole (docs/show-events-contract.md) through the **preview** of section 7,
so the firmware needs no show-event code. `app/features/pillar/poles.py` owns it.

- Pillar 1 is always **L**, pillar 2 always **R**.
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
