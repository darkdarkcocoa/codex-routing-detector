# Mascot art

The half-elf seer, made on 26 November 2026 in the look of an early-90s high-fantasy OVA. She
replaced the little hoodie detective, who had replaced the lavender cat detective.

| File | What it is |
| --- | --- |
| `source/mascot.png` | main picture: from her head to her hips, looking through the scrying lens on her staff |
| `source/icon.png` | the same picture cut to her face and the lens, for `docs/icon.ico` and the round avatar in the window |
| `source/mood_ok.png`, `mood_rerouted.png`, `mood_idle.png`, `mood_error.png` | the four moods: a calm smile with a hand on her heart, a sharp point with the lens blazing red, eyes closed in meditation under her hood, a troubled frown with the lens clouded |
| `source/mascot_anim.webp` | the idle loop (240 px, 12 frames a second, 72 frames); the READMEs show this file |
| `prompts/` | the prompts the pictures were made from |

## How they were made

The tools need Pillow and numpy. In the prompts, `<WORK_DIR>` stands for the folder the raw renders
were saved to.

1. **Pictures**: Codex CLI's built-in image generation (`codex exec` with `gpt-6.2-sol`, reasoning
   medium), each prompt file fed on stdin:
   - `candidates.txt` drew three candidates; the first, the half-elf sorceress, was picked.
   - `main.txt` and `moods.txt` drew the main picture and a 2x2 mood sheet, with the picked candidate
     cut out of the lineup and attached with `-i` as the character reference.
   - `blink.txt` edited the main picture (attached with `-i`) so that only her eyes are closed.

   The style is described in words only (a late-80s / early-90s high-fantasy OVA cel); no picture
   from an existing work was attached. Everything is drawn on flat `#00FF00`, because the generator
   paints a checkerboard when asked for transparency.
2. **Keying**: `tools/key_green.py` takes the green out (the raw renders are not kept: a rerun of the
   generator would draw something different anyway):

   ```
   python tools/key_green.py image main_raw.png art/source/mascot.png --max 384
   python tools/key_green.py image main_raw.png art/source/icon.png --crop 350,30,850,530 --max 384
   python tools/key_green.py grid moods_raw.png art/source mood_ok mood_rerouted mood_idle mood_error --max 384
   ```
3. **Animation**: `tools/make_idle_loop.py` builds the loop from the main picture and the blink edit,
   with no video model: the eyes come from the blink edit where the two pictures differ (the rest is
   pixel for pixel the same, so nothing drifts between frames), and slow breathing, a glint across
   the lens, the moonstone's pulse and motes of light rising from the staff are drawn on top. Each
   effect repeats with the loop.

   ```
   python tools/make_idle_loop.py main_raw.png blink_raw.png art/source/mascot_anim.webp
   ```

   The positions of the lens and the moonstone are fractions of the main picture, set at the top of
   the script; a new main picture needs them checked.
4. **Into the program**: `python tools/make_assets.py` embeds them in `codex_routing_assets.py`, writes
   `docs/icon.ico` and the copies in `docs/` and `design_handoff_routing_detector_ui/assets/`. Then
   `python tools/make_screenshots.py` and `python tools/make_social_preview.py` redraw the README
   screenshots and the social preview card.
