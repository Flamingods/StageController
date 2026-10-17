# Stage Emulator tab: UI redesign

Date: 2026-10-03. Companion to `2026-10-03-emulator-target.md` (what to show). This doc covers only the
layout. Clickable mockup: `emulator-ui-mockup.html` in this folder. Open it and use the "mockup state"
bar at the top, or `#idle`, `#duet`, `#showoff`, `#thunder` or `#fail` in the URL. The pillar buttons and
the ← / → keys work in it too.

## 1. Main decision

The stage drawing becomes the whole control surface for each side. Each pillar's button, its 24-segment
pole, its % readout and its per-side press chips (×1 to ×5, hold) are drawn **inside the SVG**, at the
pole they belong to. The chips use a `<foreignObject>`, so they scale with the drawing and can never drift
away from it. The viewBox gets wider, and the empty margins around the T now hold the appliance labels
(in fixed lanes) and the two side clusters. The SVG now fills its panel instead of sitting in a letterbox.
Everything else goes into one dock on the right: the test presses and the tabbed panes. The song map is
a full-width strip at the bottom. The Now banner is a full-width strip at the top.

## 2. Layout

Available height = viewport − nav (65.5 px measured) − 16 px padding. The rows are banner (~58 px),
stage (1fr) and song map (~66 px). Nothing outside the panes scrolls.

```
1280x800 and 1440x900 (dock = clamp(320px, 26vw, 400px))
+--------------------------------------------------------------------------+
| (PILL) Now: Playing Showoff · verse 2 · Right's turn · 1:02.1 | <- L next |
|        Lights: right pole blue glow ... spotlights ON (verse)  | -> R next |
+-----------------------------------------------------+--------------------+
| legend   moving lights   back lights   moving lights| LAUNCH  (3x2)      |
| flood ·-[]  .  .  .  .  .  .  .  .  .  .  .  .  []-·| BOTH    (x1-3,live)|
|        STAGE (T, perimeter LEDs, appliances)        | IN SONG (4)        |
| flick·-o                spot                    o-· +--------------------+
|        smoke            |  |            bubbles     | [Feed][Rules][Log] |
|                         |CW|                        | [Status]           |
| Left pillar [SINGING]  (L) entrance (R) [resting]   | 20:22:10 L pressed |
| click=tap, hold=stop  sing |##|      |::|  Right... |  2x -> claps       |
| [x1][x2][x3][x4][x5][hold] |##|      |::| [x1]..[h] |   -> controller ok |
| pole: lime glow            |##|      |::|           | (scrolls inside)   |
+-----------------------------------------------------+--------------------+
| Song map · 117.5 bpm · showoff  now: verse 2   [seek x4]   1:02.1 / 3:55.7 |
| [intro|v1 L|pre|chorus|v2 R|..⚡..|instr|bridge|⚡v3 L|..⚡|chorus|post|outro]|
+--------------------------------------------------------------------------+

>= 1800 px wide (2000x970): the dock splits into two columns
| banner                                                                    |
| STAGE (1fr, about 1150 px)               | PRESSES 330px | PANES 24vw     |
| song map                                                                  |
```

Fit checked in headless Chrome at 1280×800, 1440×900 and 2000×970. None of them scroll.

## 3. Hierarchy and why

1. **Stage drawing (hero).** It answers "what is the real stage doing": the poles, the perimeter and the
   appliances. It gets the most pixels, and it is where the hands are (the buttons sit on their poles).
2. **Now banner.** It answers "why" in words. Line 1 states the state, game, section, whose turn it is
   and the time. Line 2 says why the lights look the way they do. The right column says what the next
   press on each side does. It replaces the old press guide, which duplicated it.
3. **Song map.** It answers "where are we, and what is coming": turns, the cutoff and thunder.
4. **Dock.** Test presses (compact, emphasised by state), then the feed. The feed is the default tab.
   The rules, night log and status are one click away.

## 4. Regions

| Region | Content |
|---|---|
| Banner | State pill (IDLE / LAUNCHING / INTRO / PLAYING / THUNDER / FAIL with a sub-label), `nowText` + time, a "Lights:" line (`whyText`: pole colours, perimeter, appliances that are on and the rule that turned them on), and per-side "← Left next" / "→ Right next" (`nextTextFor(side)`). The live action is highlighted with `<em>`. Actions the controller would ignore are struck through. |
| Stage SVG | viewBox `-160 -60 1040 660`. T, LEDs and poles keep their current coordinates. Legend at top-left (foreignObject, `x -150 y -58 w 290`). Appliances use fixed label lanes (§7). Poles: segments `x±13 w26 h5`, step 6.5, from y 430; frame `x±17` with a `#8a7886` 2px stroke. % readout 30px, 26 units outboard at y 470. Glow shows `sing` in the owner's colour. Button: `r 27` at y 395, hold ring `r 34` (dash = hold progress), letter and arrow-key glyph inside. |
| Side cluster | foreignObject `L: x -150`, `R: x 552`, `y 395 w 318 h 200`. Contents: header "Left pillar" + role badge (SINGING / SHOWING OFF / resting / ACTIVE · TAG! / dark · may clap / pillar idle / blink), the line "click = 1 tap · quick clicks = N taps · hold 1.5 s = stop · key ←" (it changes to "3 taps…" while a gesture is pending), chips ×1–×5 and hold, and "pole: <what it shows>". |
| Presses card | **Launch** grid 3×2: Solo L×1 · Duet Both×1 · Showoff Both×2 · Thunder Both×3 · Fail L×2+R×3 · Late L×1 then R×1. **Both pillars**: ×1 ×2 ×3 + "Both live" (press = both at once, hold = stop). **In song** (left pillar): Claps ×2 · Special ×3 · Skip ×4 · Stop hold. The game name is the label and the script is the sub-label. |
| Panes | Tabs: **Feed** (default) · Light rules · Night log · Status & devices. Each tab scrolls inside itself. A feed entry is two lines: `time [L/R/L+R] what came in → **meaning**`, then `↳ controller: reply`. Ignored replies are amber. The newest entry flashes. |
| Song map | Head row: title · bpm · game · "now: <section>" · seek buttons (Skip cutoff −5 s, Next section −5 s, Verse 2 end −5 s, Thunder n/N −10 s) · time. Bar 30 px: section blocks coloured by `sectionOwner` (past 0.3 opacity, current 1.0 with a white inset, future 0.5), a red dashed cutoff with the label "skip ✕ after", a ⚡ tick at every thunder change (faint unless the game is thunder; hatched countdown-to-window span in thunder), and a glowing playhead. Click to seek. Empty state: a dashed placeholder of the same height, so the layout does not jump. |

## 5. Behaviour per state (what is emphasised)

Emphasis is one table: `buttonState(scriptId, ctx) → 'hot' | 'dim' | 'no' | null`. `hot` = accent border
and glow. `dim` = opacity .35. `no` = struck through, with the reason as a tooltip (the same text the
backend would answer).

| State | Pill | Poles / cluster badges | Hot | Dim / no |
|---|---|---|---|---|
| idle | IDLE · waiting | the pillar idle sequence; badge "pillar idle" | every Launch and Both button, side ×1–×3 | In-song buttons, side ×4/×5 dim |
| launching | LAUNCHING · counting | the presser's pole 33/66/100 % pink; badge "counting 2" | the other side's ×N equal to the presser's count (joins the game) | everything else dim; banner: "decides in 500 ms" |
| intro | INTRO · <game> 3/2/1 | 100/66/33 % in the game's colours | hold (stop) only | everything else dim |
| playing (solo/duet) | PLAYING · <game> | owner's pole glows in its colour (`sing`), the other is dim (14 %); SINGING / resting | In song, side ×2–×4, hold | Launch dim; side ×1 dim; ×4 struck after the cutoff ("past the skip cutoff") |
| playing (showoff turn) | PLAYING · showoff | as above; badge SHOWING OFF; the turn's half of the perimeter | as above | as above |
| thunder window | THUNDER · build / rush / open / window | active pole white with fill %; the dark pole off; badges ACTIVE · TAG! / dark · may clap | active ×1 (tag or early), dark ×2 (applause), hold | active ×2 struck ("active pole may not clap"), ×4 struck past the cutoff, Launch dim |
| fail | FAIL · counts differ | white blinks L, R, L, R, then the fade | nothing | everything dim; banner says "back to idle in …" |

## 6. Changes, file by file

**`frontend/src/components/StageEmulator.tsx`**
- Delete `pillar(side)` and the two HTML pillar columns. Pass the press and release handlers and the
  gesture feedback to `StageView` (new props, below).
- Delete the press guide (`<details className="press-guide-box">`), `lit()`, `GUIDE_LIT_MS` and the guide
  `row` bookkeeping. The banner and the emphasis replace them.
- Banner: `<section className="emu-now">` with the pill, `nowText(ctx)` + the time, `whyText(ctx, devices)`
  and two `nextTextFor(ctx, side)` lines. Keep the live / offline badge as a small dot in the pill.
- The side chips (×1–×5, hold) move into the `sideSlot` render prop. Delete the "Single pillar taps" group
  and the thunder Tag / Applause buttons (the side chips now carry that, emphasised).
- Presses card: `launchButtons` in a 3×2 grid with label + `<small>` script; Both ×1–×3 + Both live;
  In song ×4. Each `scriptButton` gets `className={buttonState(id, ctx)}` and a title with the reason.
- `Timeline`: one head row (title, section, seek buttons, time). ⚡ markers on `thunder_windows[].change_s`
  (faint unless `game === 'thunder'`). Keep the hatched span only for thunder. Past / current / future
  opacity. Empty state is a fixed-height placeholder.
- Tabs: rename to `Feed`, `Light rules`, `Night log`, `Status & devices`. The feed renders two-line entries
  (`pressLine` → line 1, `answerText` / `showLine` → the `↳` line). Mark ignored answers.
- Move the legend into `StageView` (`legend` prop, or build it inside StageView from `spec`).

**`frontend/src/components/StageView.tsx`**
- `viewBox="-160 -60 1040 660"`.
- `APPLIANCES` becomes a list of `{ name, label, kind, at: [x,y][], lab: [x,y,anchor][] }` with the slots in
  §7. Draw a dashed leader from each label to its fixture. The label reads `<label> ON|off`, bright when on.
  Draw beams (`.beam`, opacity .16 when on): back-light wash, moving-light cones, a spotlight cone down the
  catwalk, floodlight fans, smoke clouds and bubbles.
- Remove the texts "perimeter LEDs (dots along the edge)", "button" ×2 and "left pole/right pole" (the
  cluster headers carry them). Keep `catwalk` (rotated, `#3a2a35`), `entrance` and a small `STAGE`.
- Poles: wider segments and a visible frame (§4). `%` text at `x ± 26, y 470`. A `glow` pole shows `sing`
  in its colour. A `dim` pole draws every segment at 14 % of its colour.
- Button: `<g className="pillar-btn" role="button" tabIndex={0}>` with `cap r 27`, a `hold` ring `r 34`
  (`strokeDasharray = holdK * 214`), the letter and the arrow glyph. Pointer down / up / cancel go to the
  new `onPress(side)` / `onRelease(side)` props. Keep the lamp-lit class from `f.buttons`.
- New props: `sideSlot: (side) => ReactNode` (rendered in the foreignObject at §4 coordinates),
  `onPress`, `onRelease`, `hold: Record<Side, number>`, `pending: Record<Side, number>`. The rAF loop is
  unchanged.

**`frontend/src/show/stageLook.ts`**
- `playing()`: after `poles()`, fill the non-owner side with a dim pole
  `{ pct: 100, name: OWN[side], a: 0.14 }` (lime for L, blue for R; pink when the owner is both, which
  means both poles are already lit). Skip this during a live thunder phase (the dark pole stays off). Add
  a `dim?: true` flag to `Lit` so StageView can label it. Keep the binding numbers untouched: this only
  affects the drawing.

**`frontend/src/show/pressMeaning.ts`**
- Split `nextText` into `nextTextFor(ctx, side)`. It returns the per-side string with the live action
  wrapped for highlighting (return `{ text, live?: string, ignored?: string[] }` rather than HTML).
- Add `whyText(ctx, devices)`: pole colours and their reason, the perimeter look, and `on` appliances with
  their rule (scene table: chorus → floodlights, verse → spotlights).
- Add `buttonState(scriptId, ctx)` (the §5 table) and `poleRole(side, event)` for the badges.
  Unit-test both next to the existing `pressMeaning.test.ts`.

**`frontend/src/components/StageEmulator.css`**: replace the layout block with §8. Delete `.press-guide*`,
`.emulator-pillar`, `.emulator-pole`, `.emulator-button*` and `.emulator-side` (the HTML pillar column).
Add `.hot`, `.dim`, `.no`, the `.pillar-btn`, `.side`, `.role`, `.legend` and song map marker rules. Copy
them from the mockup's `<style>`. The class names match one to one.

**`frontend/src/components/LightRules.tsx` / `.css`**: drop the `<h3>` (the tab is the title). Show one
card per line (`grid-template-columns: 1fr`, `<b>title</b> · lines joined with " · "`) so all of them fit
in the pane at 1280×800. Keep `.active`.

No backend change is needed. `thunder_windows`, `skip_cutoff_s`, `turn` and `singer` already come from
`/api/show/songmap`.

## 7. Appliance label slots (viewBox units; none of them collide)

| Appliance | Fixture(s) | Label slot (x, y, anchor) | Lane |
|---|---|---|---|
| backLights | bar 130–590 at y 44 | 360, −22, middle | top lane |
| movingLights | (190,80), (530,80) | (190,−22) and (530,−22), middle | top lane |
| spotlights | (360,104), cone to the catwalk | 378, 108, start | inline (free span between the moving lights) |
| floodLights (x2) | (84,70), (636,70) | (22,74) end · (698,74) start | side gutters |
| flickers | (84,150), (636,150) | (22,154) end · (698,154) start | side gutters |
| smoke | (250,170) | 250, 226, middle | audience strip under the front edge |
| bubbles | (470,170) | 470, 226, middle | audience strip |

The LED outline runs x 40–680 and y 25 / 195. The gutters end at x 22 / 698, the top lane sits at y −22,
and the audience strip at y 226. Each slot keeps at least 11 units away from an LED halo (r 9).

## 8. CSS grid sketch

```css
.app:has(.stage-emulator) { height: 100vh; overflow: hidden; }            /* keep */
.stage-emulator {
  height: 100%; min-height: 0; display: grid; gap: .5rem;
  grid-template-rows: auto minmax(0, 1fr) auto;
  grid-template-columns: minmax(0, 1fr) clamp(320px, 26vw, 400px);
  grid-template-areas: "now now" "stage dock" "song song";
}
.emu-now   { grid-area: now; display: grid; grid-template-columns: auto minmax(0,1fr) minmax(0,1.1fr); }
.emu-stage { grid-area: stage; display: flex; min-height: 0; }  /* svg: flex 1, width/height 100% */
.emu-dock  { grid-area: dock; display: grid; grid-template-rows: auto minmax(0, 1fr); gap: .5rem; min-height: 0; }
.emu-panes { display: flex; flex-direction: column; min-height: 0; }
.emu-pane  { flex: 1; min-height: 0; overflow-y: auto; }
.emu-song  { grid-area: song; }
@media (min-width: 1800px) {            /* must come after the base rules */
  .stage-emulator { grid-template-columns: minmax(0,1fr) 330px minmax(400px, 24vw);
                    grid-template-areas: "now now now" "stage press panes" "song song song"; }
  .emu-dock { display: contents; }
  .emu-press { grid-area: press; } .emu-panes { grid-area: panes; }
}
```

Watch-outs found while building the mockup:
- The `@media` block must come after `.emu-dock { display: grid }`. Otherwise `display: contents` loses
  and the wide layout collapses.
- Long tab labels wrap at 1280 px. Keep them short and use `white-space: nowrap`.
- At 2000×970 the presses column has free space under it. If that bothers the user, move "Status &
  devices" out of the tabs and under the presses there. This is optional and not in the mockup.
