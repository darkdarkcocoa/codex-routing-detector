# Handoff: Codex Routing Detector — UI redesign ("Soft Sheet")

## Overview

`codex-routing-detector` is a Python desktop app (tkinter) that tells the user which model
actually answered their Codex requests. It has two tabs: **Check** (send one probe, read the
verdict) and **Live monitor** (watch a real Codex CLI session, one row per response).

The current window is drawn in a pastel "retro window" style: every panel is a canvas-drawn
window with a 2px outline, a hatched title bar, three fake window dots, sticker buttons and
sticker icons. The owner's verdict on it: cluttered, dated form controls, spreadsheet-like
results table, noisy stickers, messy alignment.

This redesign keeps every piece of information and every control, and changes the presentation:
the verdict becomes a single large hero card with the mascot in it, the table becomes an airy
list of rows, all outlines/hatching/dots/stickers are gone, and the palette is reduced to one
accent on a sage-tinted paper ground.

## About the design files

The files in this bundle are **design references written in HTML/CSS** — prototypes that show
the intended look and behaviour. They are not production code to copy. The task is to recreate
them in the app's own environment.

Two routes, pick one:

1. **Port to tkinter** (keeps the current stack, `codex_routing_detector_gui.py`). Feasible but
   lossy: tkinter has no soft shadows, no CSS transitions, no border-radius on widgets. Rounded
   cards and the pill buttons must be drawn on `tk.Canvas` (the file already does this in
   `RoundedButton` / `RetroPanel` / `rounded_rect()` — reuse those primitives with the new
   tokens). Animations must be driven by `root.after()` loops. Drop the floating sparkles and the
   confetti; keep the character's idle/running/result motion as a simple `after()` tween on a
   canvas image.
2. **Move the UI to a webview** (`pywebview` + this HTML, Python keeps all the logic). The
   owner has approved this route. All motion, shadows and radii come for free; the Python side
   exposes `run_check()`, `start_live()`, `stop_live()` and pushes rows/verdicts to JS. This is
   the recommended route if the motion design matters.

Whichever route, the layout, tokens and copy below are the spec.

## Fidelity

**High fidelity.** Colors, type sizes, spacing, radii, shadows, animation durations and easings
are all final and listed below. Recreate pixel-accurately at a 1180px-wide window. Contrast was
checked against WCAG AA (4.5:1 body, 3:1 for ≥24px or ≥18.66px bold) — do not lighten any ink
token listed here.

## Screens / views

The window is a single 1180px-wide column, `border-radius: 24px`, background `#f4f6f2`,
`box-shadow: 0 24px 60px rgba(47,58,51,.16)`. There is no OS-style title bar in the design; the
app's own header is the top of the window.

Behind everything sits a decorative sparkle layer: `position: absolute; inset: 0;
pointer-events: none; overflow: hidden`, holding 8 small glyphs (`✦ ✧ · ✦ ✧ • ✦ ✧`), font-size
9/14/19px, colors `#bfe0ea` / `#d9cfee` / `#cfe6d8` cycling, each animated `floatUp` for
7–14.5s with a 0.9s-per-item stagger, infinite. Purely decorative — skip it in a tkinter port.

### 1. Header (both tabs)

`display: flex; align-items: center; gap: 12px; padding: 20px 32px 0`

| Element | Spec |
|---|---|
| Mascot | `assets/mascot_256.png`, 40×40, `object-fit: contain` |
| App name | "Codex Routing Detector", 17px / 700 / `letter-spacing: -0.2px` / `#2f3a36` |
| Subtitle | KO "내 요청에 실제로 답한 모델은?" · EN "Which model really answered your request?", 12.5px / `#5f6b65` |
| Language toggle | white pill, `border-radius: 999px; padding: 5px; box-shadow: 0 1px 3px rgba(47,58,51,.08)`; two segments 12px/600, `padding: 4px 11px`, radius 999px; active segment = accent fill + `#ffffff` ink, inactive `#5f6b65`. Click toggles ko/en |
| Help button | 34×34 circle, white, same shadow, "?" 15px/700 `#5f6b65`; hover ink = accent |

The toggle switches **every** string in the UI, help texts included (the current app already has
full ko/en tables in `STRINGS` — reuse them).

### 2. Tab bar (both tabs)

`display: flex; gap: 26px; padding: 18px 32px 0`. Each tab: `padding: 10px 2px 14px`, 14px/700,
selected `#2f3a36`, unselected `#5f6b65`. Selected tab has a 3px `border-radius: 999px` bar
pinned to its bottom in the accent color. To the right of the tabs, a `flex: 1` 1px line in
`#e4e9e2`, vertically centered.

Page content below animates in with `slideTab` (0.32s ease-out) on every tab change.

### 3. Hero verdict card (both tabs, top of page)

`display: flex; align-items: center; gap: 22px; border-radius: 24px; padding: 26px 28px;
box-shadow: 0 2px 14px rgba(47,58,51,.07)`, entering with `bopIn` (0.5s
`cubic-bezier(.2,.9,.3,1.3)`).

Background and heading ink are the state signal:

| State | Card bg | Heading ink | Ring | Character motion |
|---|---|---|---|---|
| idle / monitor off | `#ffffff` | `#2f3a36` | `#cfe6d8` at 45% opacity | `idleBreath` 3.4s |
| running / watching | `#eef6fa` | `#1f5b70` | `#9fd8e8`, `pulseRing` 1.6s | `sniff` 0.9s |
| rerouted | `#fdf0f0` | `#a8323b` | `#f3bfc1` at 45% | `bounce` 2.6s |
| ok | `#eff9f3` | `#1f6f52` | `#cfe6d8` at 45% | `idleBreath` 3.4s + confetti |

Left column: 150px wide, `display: grid; place-items: center`. Contains the character
(`mascot_256.png`, 124×124, `object-fit: contain`) and, behind it, a ring — an absolutely
positioned 142×142 circle, `border-radius: 999px`, `border: 2px solid <ring color>`.

Right column (`flex: 1`, `gap: 10px`):

1. Status row: the verdict chip + a monospace status line 12.5px `#5f6b65`
   (idle "준비됨" / running "probe 1/1 · gpt-6-astra (low)" / done "7.3초 소요").
   Chip: 11.5px/700, `letter-spacing: .3px; padding: 4px 11px; border-radius: 999px`.
   - idle `#eef1ec` bg / `#4f5a55` ink · running `#d9edf5` / `#1f5b70`
   - rerouted `#fadcdd` / `#a8323b` · ok `#d8f0e4` / `#1f6f52`
2. Headline: 28px/700, `letter-spacing: -.4px`, ink per table above.
3. Briefing paragraph: 14.5px, `line-height: 1.6`, `#55605b`, `max-width: 760px`,
   `text-wrap: pretty`. Copy is in "Copy" below; it is the existing `build_brief()` output,
   rewritten in a friendlier voice.
4. Action row: primary pill + (while running) the walker progress bar.
   - Primary pill: accent fill, `#ffffff` ink, `border-radius: 999px; padding: 11px 26px`,
     14.5px/700, `box-shadow: 0 4px 12px rgba(47,58,51,.14)`,
     `transition: transform .12s ease, filter .12s ease`; hover `filter: brightness(1.05)`;
     active `transform: translateY(2px) scale(.98)`. Disabled/running: fill `#e7ece6`, ink `#5f6b65`.
   - Walker: 250×30 wrapper; track `height: 8px; border-radius: 999px; background: #e7ece6`,
     bottom-aligned; fill 45% wide, `linear-gradient(90deg,#9fd8e8,<accent>)`, animated `walk`
     2.4s ease-in-out infinite alternate; a 30×30 mascot image rides the same `walk` timing plus
     `bounce .5s infinite`.

Confetti (ok state only): 14 pieces, 5–9px wide, 7–11px tall, `border-radius: 2px`, colors
cycling `#8fd3bb #f3c3cf #bfe0ea #f0dda2 #cfc3ee`, each with a CSS var `--dx` between −60 and
+60px and `--rot` 180–700deg, animation `confetti` 1.5–2.55s ease-in, 0.06s stagger, spawning
at 60px/40px inside the hero.

### 4. Setup strip (Check tab) / Session strip (Live tab)

One row, `display: flex; align-items: center; gap: 8px; padding: 2px 4px`. Leading label 12px/600
`#5f6b65` ("설정" / "세션"). Then white pills: `border-radius: 999px; padding: 7px 8px 7px 14px;
box-shadow: 0 1px 3px rgba(47,58,51,.07)`, 13px/600; inside each, the field name in `#5f6b65`
weight 500 and the value in `#2f3a36`; a 9px `▼` in `#7a857f` where the pill is a dropdown.
Hover: `box-shadow: 0 2px 8px rgba(47,58,51,.12)`.

- Check tab pills: **모델** `gpt-6-astra` (dropdown, from `listed_models()`), **노력** `low`
  (dropdown, low/medium/high/xhigh), **반복** with `−` / value / `+` (18px circles, `#f1f4f0` bg,
  `#55605b` ink, hover `#e4ece8` + accent ink; range 1–10), **Wire 모드** as a 26×15 toggle
  (`#eceff0` track, 11px white knob, `box-shadow: 0 1px 2px rgba(0,0,0,.15)`) — disabled when
  mitmdump is missing, exactly as today.
- Right end: `margin-left: auto`, 12px monospace `#5f6b65`, "codex · auto" (or the picked binary).
  Clicking it opens the Codex-binary picker that the "Codex..." button does today.
- Live tab pills: **모델** `gpt-6-astra`, **노력** `high`, `config.toml` (opens the file),
  and at the right end the proxy address (`127.0.0.1:55198` or `—`).

### 5. Results card (both tabs)

White, `border-radius: 20px; padding: 6px 8px 10px; box-shadow: 0 2px 10px rgba(47,58,51,.06)`.

Header row (`padding: 14px 16px 10px`): title 14px/700 `#2f3a36` ("응답 기록"), a count badge
(12px/600 `#5f6b65` on `#f2f5f1`, radius 999px, `padding: 3px 9px`), then right-aligned quiet
buttons — Check tab: 보고서 복사 / JSON 저장 / 로그 폴더; Live tab: 보고서 복사 / 지우기.
Each: 12px/600 `#5f6b65` on `#f4f6f2`, radius 999px, `padding: 5px 11px`, hover ink = accent.
These map 1:1 to today's `copy_report`, `save_json`, `open_logs`, `copy_live`, `clear`.

Column grid (header and rows share it):
`grid-template-columns: 30px 88px 1fr 104px 88px 188px; gap: 12px`.
Header labels 11.5px/600 `#5f6b65`, `padding: 0 18px 8px`:
`#` · 종류 · 요청 → 실제 응답 · 상태 · 시각 · 응답 ID.

Row: `padding: 13px 18px; border-radius: 14px; margin-bottom: 6px`, background `#fdf1f1` when
rerouted and `#f2faf6` when served correctly. `transition: transform .18s ease`, hover
`translateY(-1px)`. Entering rows animate `rowIn` 0.34s `cubic-bezier(.2,.9,.3,1.2)` with a 90ms
stagger — in the live monitor that is what makes a new response slide in.

Cells:
- index badge: 24×24 circle, `#ffffff` ink 11.5px/700, fill `#b23a44` (rerouted) / `#27805f` (ok)
- kind chip: 11.5px/600 `#55605b` on `#ffffff`, radius 999px, `padding: 3px 10px`, left-aligned
- route: 14px/600 — requested `#55605b`, arrow `→` 13px (`#b23a44` rerouted / `#6f7d77` ok),
  served 700 weight (`#b23a44` rerouted / `#257a59` ok)
- status: 12.5px/500 `#5f6b65`
- time: 12.5px monospace `#5f6b65`
- response id: 11.5px monospace `#55605b`, `white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis` (full id goes to the clipboard via 보고서 복사)

Empty state: centered column, `padding: 34px 0 30px`, `mood_idle_56.png` at 46×46 with
`idleBreath` 3s and `opacity: .85`, plus 13px `#5f6b65` text
("아직 검사하지 않았어요. 버튼 한 번만 눌러 주세요." / live: "Codex 창에서 뭐든 입력하면 여기에 한 줄씩 쌓여요.").

### 6. Details disclosure (Check tab)

White, `border-radius: 18px`, same card shadow, `overflow: hidden`. Collapsed header:
`padding: 14px 18px`, 13px/700 `#6b7671`, hover ink = accent; a `▸` caret `#7a857f` that rotates
90° with `transition: transform .2s ease`; after the label, a 500-weight hint `#5f6b65`
("계정 · Codex 경로 · 로그 위치"). Expanded body: `padding: 0 18px 18px` wrapping a `<pre>` at
`padding: 14px 16px; background: #f6f8f5; border-radius: 12px`, 12px monospace,
`line-height: 1.7`, `#55605b`, `white-space: pre-wrap`. Content = today's Details text
(account/plan/usage, codex path + version + mode, log directory).

### 7. Footer

`display: flex; align-items: center; gap: 12px; padding: 4px 34px 22px`, 11.5px `#5f6b65`:
version (monospace, turns into the NEW badge on an available update — keep today's behaviour and
`#b3261e` color), a GitHub link in `#1f6070`, and a right-aligned one-liner
("짧은 프롬프트 하나만 보내고, 서버가 적어 보낸 모델명을 읽어요.").

## Interactions & behaviour

- **Tab switch** — instant; page content replays `slideTab`. Tab tone is per-tab: the Live tab
  must never inherit the Check tab's verdict colors (an idle monitor stays neutral white).
- **Check** — press → `running` (hero turns blue, character sniffs, ring pulses, walker appears,
  rows clear) → on completion `done` with the verdict tone, rows stagger in, ok adds confetti.
  Keep today's confirm dialog ("한 번만 묻기" checkbox) before the first probe.
- **Cancel** — the old separate Cancel button is gone; while running the primary pill is the
  disabled "검사 중..." state. Put Cancel where you prefer (a quiet text button next to the
  walker is the intended spot) — the capability must stay.
- **Live monitor** — Start opens the Codex window and the hero switches to watching; each
  response appends a row (`rowIn`) and updates the hero + briefing totals. Stop asks for
  confirmation (it closes the watched Codex window), then returns the hero to the neutral off
  state and keeps the rows until 지우기.
- **Language toggle** — swaps all strings immediately, no relayout.
- **Details** — click anywhere on the header row to expand/collapse.
- **Hover/active** — pills brighten and sink (`translateY(2px) scale(.98)`); rows lift 1px; quiet
  buttons switch ink to the accent.
- **Responsive** — the window is a fixed 1180px design (the app's min size today is 1000×800).
  Only the route column (`1fr`) and the briefing paragraph need to flex.

## State management

Same state the current GUI already keeps, minus the panel chrome:

| State | Values | Set by |
|---|---|---|
| `tab` | `check` \| `live` | tab bar |
| `lang` | `ko` \| `en` | language toggle (persist in the settings file, as today) |
| `phase` | `idle` \| `running` \| `done` | Check / worker thread |
| `verdict` | `ok` \| `REROUTED` \| `ERROR` \| `UNSUPPORTED` \| `UNKNOWN` \| `NO_DATA` \| `CANCELLED` | `CheckResult.overall` |
| `rows` | list of `{n, kind, requested, served, status, time, rid}` | probe responses |
| `liveOn`, `liveRows` | monitor running + one row per response | `codex_routing_live` events |
| `detailsOpen` | bool | disclosure |

The prototype only paints `ok` / `REROUTED` / running / idle. The remaining verdicts reuse the
same hero shape — map `ERROR`, `UNSUPPORTED`, `UNKNOWN`, `NO_DATA` to an amber tone
(bg `#fdf6ec`, ink `#8a5a12`, chip `#f7e6c8` / `#8a5a12`) and `CANCELLED` to the idle tone, with
`mood_error_56.png` as the empty-state picture. Their briefing and advice strings already exist
in `STRINGS`.

## Design tokens

**Ground / surface**

| Token | Value | Use |
|---|---|---|
| paper | `#f4f6f2` | window background |
| card | `#ffffff` | all cards, pills |
| hairline | `#e4e9e2` | tab rule |
| chip ground | `#f2f5f1` | count badge |
| quiet button | `#f4f6f2` | text buttons on card |
| control ground | `#f1f4f0` | stepper circles |
| pre ground | `#f6f8f5` | details block |
| disabled fill | `#e7ece6` | running pill, progress track |

**Ink**

| Token | Value | Use |
|---|---|---|
| ink | `#2f3a36` | titles, values |
| body | `#55605b` | paragraphs, table text |
| muted | `#5f6b65` | labels, meta, footer |
| faint | `#6b7671` / `#7a857f` | disclosure header / carets (decorative) |

**Accent + state**

| Token | Value | Notes |
|---|---|---|
| accent | `#2a7d96` | primary pill, active toggle, tab bar, hover ink. White on it = 4.7:1 |
| accent link | `#1f6070` | text links on paper |
| accent gradient | `#9fd8e8` → accent | progress fill only |
| running bg / ink / chip | `#eef6fa` / `#1f5b70` / `#d9edf5` | |
| ok bg / ink / chip / badge / served | `#eff9f3` / `#1f6f52` / `#d8f0e4` / `#27805f` / `#257a59` | row tint `#f2faf6` |
| rerouted bg / ink / chip / badge / served | `#fdf0f0` / `#a8323b` / `#fadcdd` / `#b23a44` / `#b23a44` | row tint `#fdf1f1` |
| idle chip | `#eef1ec` / `#4f5a55` | |
| rings | `#9fd8e8` (running) · `#f3bfc1` (rerouted) · `#cfe6d8` (else) | |

Alternate accents that keep white text legible (offered as a tweak in the prototype):
`#6f5bc9`, `#c4557a`, `#27805f`.

**Type** — Quicksand 400/500/600/700 for latin, Gowun Dodum for Korean, JetBrains Mono for ids,
times and paths. Sizes: 28 (verdict) · 17 (app name) · 14.5 (body, primary pill) · 14 (tabs,
route) · 13 (pill values, disclosure) · 12.5 (meta) · 12 (quiet buttons, toggle) · 11.5 (chips,
column headers, response id). In a tkinter port substitute the closest installed faces (Segoe UI
Variable / Malgun Gothic / Consolas on Windows) and keep the sizes.

**Spacing** — 2 · 4 · 6 · 8 · 10 · 12 · 14 · 18 · 22 · 26 · 32. Page padding `20px 32px 10px`,
gap between cards 14px.

**Radius** — 24 (window, hero) · 20 (results card) · 18 (details card) · 14 (row) · 12 (pre) ·
20 (mood slot) · 999 (all pills, chips, badges).

**Shadow** — window `0 24px 60px rgba(47,58,51,.16)` · hero `0 2px 14px rgba(47,58,51,.07)` ·
card `0 2px 10px rgba(47,58,51,.06)` · pill `0 4px 12px rgba(47,58,51,.14)` · control
`0 1px 3px rgba(47,58,51,.07)` · control hover `0 2px 8px rgba(47,58,51,.12)`.

**Motion**

| Name | Spec | Used by |
|---|---|---|
| `bopIn` | 0.5s `cubic-bezier(.2,.9,.3,1.3)`, scale .82→1.04→1 + 14px rise | hero card |
| `rowIn` | 0.34s `cubic-bezier(.2,.9,.3,1.2)`, −14px x-shift + fade, 90ms stagger | result rows |
| `slideTab` | 0.32s ease-out, 22px x-shift + fade | page on tab change |
| `sniff` | 0.9s ease-in-out infinite, ±3° + 4px bob | character while checking |
| `bounce` | 2.6s (character) / 0.5s (walker) ease-in-out infinite, 9px | character on rerouted |
| `idleBreath` | 3.4s ease-in-out infinite, scale 1→1.025 | character at rest |
| `pulseRing` | 1.6s ease-out infinite, scale .7→1.45 + fade | ring while checking |
| `walk` | 2.4s ease-in-out infinite alternate, left 0→100%−30px | progress fill + walker |
| `confetti` | 1.5–2.55s ease-in, translate(`--dx`, 190px) + rotate(`--rot`) | ok celebration |
| `floatUp` | 7–14.5s ease-in-out infinite, −46px rise + fade | background sparkles |
| hover/press | `transform .12s ease`, `filter .12s ease`; rows `transform .18s ease` | pills, rows |

## Assets

All from the existing app — `codex_routing_assets.py` embeds them as base64 PNG; this bundle
carries them as files under `assets/` (extracted, unmodified):

| File | Used at | Notes |
|---|---|---|
| `mascot_256.png` | hero 124×124, header 40×40, walker 30×30 | a 512px source would be sharper for the hero |
| `mood_idle_56.png` | empty state 46×46 | |
| `mood_ok_56.png`, `mood_rerouted_56.png`, `mood_error_56.png` | reserved for the verdict states | not currently placed in the layout |
| `sticker_*.png` | **dropped** | the sticker icons are not part of this design |

The mascot is the app's own lavender cat detective, made with image generation and rebuilt by
`tools/make_assets.py`. New poses (sniffing, walking side view, sleeping, blinking) were
requested but not delivered yet; the design works with the single pose.

## Files

| File | What it is |
|---|---|
| `Redesign A - Soft Sheet.dc.html` | **the design.** Interactive: press 검사하기 to run the fake check (alternates rerouted/ok), switch tabs, toggle 한국어/EN, expand 상세 정보 |
| `Current UI (recreation).dc.html` | pixel recreation of today's tkinter window, for before/after |
| `Redesign B - Companion.dc.html` | the direction that was not chosen (cat speaks in a speech bubble). Reference only |
| `support.js` | runtime the three HTML files need; keep it next to them |
| `assets/*.png` | the pictures listed above |
| `source-notes.md` | where each value in the current app comes from (`PALETTE`, `RetroPanel`, `STRINGS`, …) |

Open the HTML files directly in a browser from the folder root.
