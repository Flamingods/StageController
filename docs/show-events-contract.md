# Show events contract (StageController -> StagePillar / StageLeds)

Version 1 -- 2026-10-03. Numbers and colours come from the stage spec
(`backend/app/features/show/spec.json`); this file only describes the wire. Change it first.

## 1. Posting a gesture (pillar -> controller)

`POST /api/buttons/press` keeps its body and action names (`start|stop|skip|claps|special`).
Three **optional** fields join the show state machine:

| field | meaning |
|---|---|
| `side` | `"L"` or `"R"` (left/right as seen standing at the entrance facing the stage). Present = side-aware press handled by the show director. Absent = legacy single-button path, unchanged. |
| `taps` | the gesture's real tap count (>= 1). The action name is lossy (4 = `skip`, 5+ = `special` = 3), so a pillar that knows the count should send it; the launch rule then counts `taps`, not the action. Absent = the count the action stands for. |
| `first_press_ago_ms` | ms between the gesture's **first** press and the moment the request is sent. The controller reconstructs `first_press = arrival - first_press_ago_ms`; two pillars are "together" when their first presses are within `syncWindowMs`. Default 0. |

Idle: the action name stands for the tap count (`start` 1, `claps` 2, `special` 3, `skip` 4;
`special` also covers 5+) and feeds the launch rule. A long press (`stop`) while idle turns
everything off. In song the meaning comes from `taps` when present (user rule 2026-11-01):
1 = tap, 2 = claps, **3 = skip**, **4+ = special**; a long press (`stop`) is stop. The pillar's
action names are not changed (it still sends 3 taps as `special`, 4 as `skip`): the controller
reads the count. Without `taps` the action name keeps its old meaning.

Response for a side-aware press: `{"status":"ok","action":..,"side":..,"show_state":..}` or
`{"status":"ignored",...,"reason":..}`.

## 2. Event envelope (controller -> clients)

Same socket as button events: `ws://<host>/api/buttons/ws`. Show events have `"action": "show"`
(button events keep `start|stop|...`; clients that do not know `show` must ignore it).

```json
{"action":"show","timestamp":"2026-10-03T20:15:01.123","state":"intro","game":"showoff","step":2,
 "poles":{"L":{"pct":66,"color":"lime","mode":"solid","ms":null},
          "R":{"pct":66,"color":"blue","mode":"solid","ms":null}},
 "perimeter":{"look":"intro","color":"blue","side":"R"},
 "song":null,"thunder":null}
```

Every show event carries the **full** pole state: a client that joins late is correct after one
message, and an event never needs the one before it. Poles light from the bottom up, toward the
button; `pct` is the fill (0-100), binding. `perimeter` is a hint (spec: illustration); absent = no
perimeter instruction.

- `color`: palette name `pink | lime | blue | white` (or `null` when off). Resolve through the
  spec's palette ramps; apply the colour tunables (gain, drift) on the LED side.
- `level` (optional, `glow` only): the brightness 0-100 of a glow (`ambientGlowPct`, 35 by default).
- `mode`: `glow` (the in-song ambient light: full height, dimmed to `level`, so it never reads as a
  binding fill) | `solid` (hold at `pct`) | `pulse` (at `pct`; `ms` = one pulse when set, else your own rate) |
  `blink` | `drain` (fall from `pct` to 0 over `ms`) | `off`.
- `perimeter.side`: `L | R | both | centre`; `look`: `intro | merge | turn | blackout`.

## 3. States

| `state` | when | poles |
|---|---|---|
| `idle` | nothing running (also after a song, a stop or a failed launch) | all `off`. **Fall back to your own slot sequences** (idle rainbow, start comet, ...) exactly as without a show. |
| `launching` | after each launch gesture, until the decision | the presser's pole at `launchPcts[count-1]` (33/66/100), pink, solid; the other pole as it was |
| `intro` | the 3-2-1 of a two-pillar game (duet, showoff, thunder), `step` 3 then 2 then 1, one event per `introStepMs`; **solo has no intro**: `launching` goes straight to `playing` | `polePcts` (100/66/33) in the game's colours, see below |
| `playing` | the song started, and again whenever the song's section, the showoff turn or the pole owner changes | the in-song glow (below), or in thunder the steal loop's poles (below); `song` set (see below) |
| `failing` | mismatched launch: `failBlinkCount` events alternating L, R, L, R each `failBlinkMs` (white, solid), then one `drain` event (`ms` = `failFadeMs`) on the last lit pole, then `idle` | one white pole at a time |

`game`: `solo | duet | showoff | thunder` (absent while launching/failing/idle).

Intro per game (solo has none, asked for by the user 2026-11-01: one pillar starts the song at once;
solo is symmetric: an L and an R launch give identical song events, only the launch fill above and
the logged side differ): duet -- both poles pink, perimeter `both`; showoff -- L lime / R blue, perimeter lime-left at 3, blue-right at 2,
then both poles pink with `perimeter.look = "merge"` at 1; thunder -- both poles white,
perimeter L at 3, R at 2, centre at 1. Launch-fill colour (pink) is a placeholder: the spec only
fixes the percentages.

When a game's song starts the controller first broadcasts the **legacy** button event
`{"action":"start","playlist_name":"<game>"}` (exactly what a plain start press sends), then the
first `playing` show event. Clients that only know legacy actions (StageLeds, pillar firmware)
therefore enter their "play" look as before; a later `idle` show event is followed by the
existing legacy `stop` on song end.

`playing` events carry `song`: `id`, `section` (the analyzer's label: `intro | verse | chorus |
bridge | instrumental | outro`, `null` when the song has no sidecar markers), `section_index`
(the analyzer's running number for that label), `t` (song seconds when the event was sent).
Showoff only: `turn` = `L | R | both` -- verses alternate L, R, L ...; every other section and the
last section is `both` -- with `perimeter = {look: "turn", color: lime | blue | pink, side: turn}`.
Other games send `turn: null`.

In-song pole glow (a deviation from the spec's 0 % after the intro, asked for by the user): every
`playing` event of solo, duet and showoff carries the poles as `mode: "glow"`, `pct: 100`,
`level: ambientGlowPct`, in the colour of whoever owns the section, the side not owning it `off`:

| game | owner | poles |
|---|---|---|
| solo | nobody (no turns) | both pink |
| duet | the singer: sidecar section `turn` (`L`/`R`/`both`, optional, hand-tagged), else the showoff alternation; the final section is always `both` | L = left lime, R = right blue, both = both pink |
| showoff | `turn` | as duet |

`playing` events also carry `buttons` -- the pillar button rings -- `{L, R, pulses, pulse_ms}`:
`L`/`R` the singer's colour per side as above (`null` = dim, the side not singing). At a change of
singer (the owner above changes: duet/showoff L -> both -> R ...) that one
event has `pulses = handoverPulses` (3) and `pulse_ms = handoverPulseMs` (1000): both buttons
pulse **together**, easing in and out, that many times over `pulse_ms`, then settle on the new
colours. Every other event has `pulses = 0`; it does not cut a running pulse short. The first
event of a song never pulses. (Both tunables added by Tom, 2026-10-03; not in the spec.)

A turn event is sent at the section boundary (within one ~20 ms
tick), not ahead of it. Fields already in the schema are stable; unknown fields must be ignored.

Section scene: on each section change the controller itself switches the appliances --
`floodLights*` on in a `chorus`, `spotlights*` on in a `verse`, both off in every other section
(names matched case-insensitively by prefix; `backend/app/features/show/scene.py`). This adds no
show-event field: the switching shows up in the devices API (`is_on`) like any other device change.

### Cue (claps)

When the controller runs the claps sequence (2 taps in song, any game, either side) it first sends
`{"action":"cue","timestamp":..,"cue":"claps","side":"L"|"R"|null}`. A cue is one-shot (a client may show a badge or play a sound);
it carries no light state and is not replayed to late joiners. Emulator only: the browser plays
`frontend/public/sounds/claps.mp3`; the Pi never plays it.

### Thunder: the steal loop

User rule, 2026-10-03; it replaces the spec's beat-based countdown and windows (spec.json
`thunder`). Thunder runs by the clock, independent of the song and its sections; the sidecar is not
used. Left performs first; the state restarts with left on every song (and after a skip).

- The **performer**'s pole: 100 %, `solid`, the performer's colour (L lime, R blue).
- The **rival**'s pole rises 0 -> 100 % in the rival's colour over `cooldownMs` (20 s by default,
  the single source is spec.json), `solid`.
- At 100 % the rival's pole switches to `pulse` with `ms = 1000 / flickerHz` (500 ms at 2 Hz): a
  full fade up and down. A steal is open, with no timeout.
- `perimeter = {look: "turn", color: <performer colour>, side: <performer>}`.

Every `playing` event in thunder carries `thunder = {phase, performer, pct}`:

| `phase` | when | poles |
|---|---|---|
| `cooldown` | the rival's pole is rising; one event per whole percent | performer 100 solid, rival `pct` solid |
| `ready` | the rival's pole is full, until they press | performer 100 solid, rival 100 `pulse` |
| `steal` | `stealBlackoutMs` (300) after a steal; `performer` is already the new one | both `off`, `perimeter.look = "blackout"` |

`buttons` in thunder: `L`/`R` = each player's colour, `flicker` = the side whose ring flickers
with its pole (`ready` only, else `null`); `pulses` stays 0 (no handover pulse on a steal: it has
its own blackout and smoke).

Presses in thunder (side-aware POSTs):

- `start` (1 tap) from the rival while `ready` = **steal**: the roles swap, the `steal` blackout
  goes out at once, the smoke puff (the `special` device sequence) runs in the background, then
  the cooldown restarts from 0 for the side that lost the stage. Logged as `press kind=steal` and
  `steal {songId, from, to, waitedMs}` (`waitedMs` = time from 100 % to the press).
- `start` from the rival before 100 % is ignored: `{"status":"ignored","reason":"too_early","pct":..}`
  (`stealBeforeFull = true` turns it into a steal). Logged as `press kind=early`.
- `start` on the performer's own pole is ignored: `{"status":"ignored","reason":"performer"}`.
- `claps`, `special`, `skip`, `stop`: as in every song.

Skip in song is accepted until the middle of verse 2 (`skipFallbackMs` without markers); later
skips answer `{"status":"ignored","reason":"after_cutoff"}`.

## 4. Ordering and latency

- Events are sent in the order the controller decided them; WebSocket keeps them ordered. The
  controller ticks every ~20 ms, so an intro step lands within ~20 ms of its due time plus
  network. Do not time steps yourself: draw the latest event until the next one arrives.
- `pct`/`mode`/`ms` are the only binding LED numbers. If a client misses a `drain` end it just
  waits for the next event.
- A skipped song, a stop or a song end during the show produces an `idle` event.
- A client that connects to the socket mid-show first receives the last show event, so it never
  draws a stale idle while the controller is playing.
- `GET /api/buttons/recent` returns the last events (button and show events mixed).
