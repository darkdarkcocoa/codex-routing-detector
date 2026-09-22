# Source notes — where today's UI lives

Read before porting. All paths are relative to the repo root (`codex-routing-detector/`).

| Repo file | What it owns | What the redesign changes |
|---|---|---|
| `codex_routing_detector_gui.py` | the whole window | see below, per section |
| `codex_routing_detector.py` | the check itself (`run_check`, `CheckResult`, `Probe`, verdicts, report/JSON text, update check) | unchanged |
| `codex_routing_live.py` | live monitor: turns proxy events into rows, starts/stops the Codex window | unchanged |
| `codex_routing_proxy.py` | CONNECT proxy + per-session CA, WebSocket frame decoding | unchanged |
| `codex_routing_assets.py` | base64 PNGs (mascot, moods, stickers) | stickers become unused |
| `tools/make_assets.py` | rebuilds the asset module + `docs/icon.ico` from source PNGs | add new poses to `SIZES` if new art arrives |

## Landmarks in `codex_routing_detector_gui.py`

| Symbol | Line-ish | Role | Redesign |
|---|---|---|---|
| `PALETTE`, `PASTEL` | ~444 | old blush/lavender tokens | replaced by the token table in README.md |
| `VERDICT_STYLE`, `VERDICT_MOOD`, `VERDICT_COLORS` | ~453 | verdict → (bg, fg, glyph) and verdict → mascot mood | keep the mapping, swap the values; the ✔/✖/⚠/• glyphs are dropped (the chip carries the wording) |
| `STRINGS` | ~47 | full ko/en string tables | reuse as is; the redesign only rewords the briefing/idle lines (see README "Copy") |
| `HELP_USAGE`, `HELP_TERMS`, menu tables | ~400 | help texts and the Help menu | unchanged; the "?" button in the new header opens them |
| `build_brief()` | ~615 | composes the briefing sentences from a `CheckResult` | unchanged; output lands in the hero paragraph |
| `rounded_rect()` | ~640 | smooth polygon helper on a canvas | reusable for the new cards in a tkinter port |
| `RoundedButton` | ~660 | sticker pill button (outline + offset shadow) | keep the class, drop `OUTLINE_W`/`SHADOW`, restyle via `BUTTON_STYLES` |
| `BUTTON_STYLES` | ~648 | per-kind fill/ink for normal/hover/disabled | new values: primary = accent `#2a7d96` + white; quiet = `#f4f6f2` + `#5f6b65`; disabled = `#e7ece6` + `#5f6b65` |
| `RetroPanel` | ~767 | the pastel "retro window" card: hatched title bar, 3 dots, 2px outline, 4px offset shadow, sticker | **removed.** Cards become plain rounded surfaces with a soft shadow and a text title inside the body |
| `App.STICKERS` | ~1063 | panel title → sticker image | removed |
| `App._card()` | ~1066 | builds a `RetroPanel` and returns its body | replace with a plain card factory |
| `App._build()` | ~1080 | Check tab layout: header, tab bar, Options, action row, banner, Briefing, Results tree, Details, bottom buttons, footer | rebuilt per README sections 1–7 |
| `App._banner()` | ~1245 | the outlined verdict banner with mood image | merged into the hero card |
| `App._build_live()` | ~1255 | Live tab: Session panel, start/stop, banner, Briefing, Results tree, Details, buttons | rebuilt; note the per-tab tone rule |
| `apply_theme()` | ~977 | ttk `clam` restyle: Treeview, Combobox, Spinbox, Progressbar, Scrollbar, Notebook | Treeview is dropped for a row list; comboboxes/spinbox become pill controls |
| `tint_title_bar()` | ~840 | paints the Windows 11 title bar pink via DWM | keep, retint: caption `#f4f6f2`, text/border `#2f3a36` |
| `load_image()` | ~855 | base64 → `tk.PhotoImage`, process-cached | unchanged |
| `ConfirmDialog` | ~880 | "we are about to send one prompt" modal with don't-ask-again | keep the behaviour, restyle to the new card/pill tokens |
| `settings_path()`, `load_settings()`, `save_settings()` | ~470 | `~/.codex-routing-detector.json` (skip_confirm, live_dir, guide seen) | unchanged; add the language choice if it is not stored yet |
| `listed_models()` | ~490 | model slugs from Codex's `models_cache.json`, else `FALLBACK_MODELS` | feeds the 모델 pill dropdown |
| `install_fake_runner()`, `feed_fake_live()` | ~510 | `--fake` / `--fake-live` fixture modes used by tests and screenshots | keep working — `tests/test_gui.py` and `tests/test_gui_live.py` drive the window through them |

## Things not to break

- `tests/test_gui.py` builds the window off-screen and asserts on widget attributes, including
  `app.lbl_version.cget("fg") == "#b3261e"` for the NEW badge. Renaming widgets means updating
  the tests.
- The confirm dialog before a probe and the stop confirmation in the live tab are there because
  both actions have side effects (usage cost / closing the user's Codex window).
- `--fake --auto-check` and `--fake --fake-live` are how the README screenshots are produced.
- The window's current geometry is `1180x960`, min `1000x800`. The redesign is drawn at 1180
  wide; keep the min size or raise it.
