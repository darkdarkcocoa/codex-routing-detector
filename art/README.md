# Mascot art

The little hoodie detective, made on 30 October 2026. She replaced the lavender cat detective.

| File | What it is |
| --- | --- |
| `source/mascot.png` | main picture: peeking through the magnifying glass and waving |
| `source/icon.png` | the same picture cut to her head, for `docs/icon.ico` |
| `source/mood_ok.png`, `mood_rerouted.png`, `mood_idle.png`, `mood_error.png` | the four moods: thumbs up, surprised point, sleepy yawn, teary |
| `source/mascot_anim.webp` | the idle loop (200 px, 12 frames a second, 69 frames); the READMEs show this file |
| `prompts/` | the prompts the pictures and the video were made from |

## How they were made

The tools need Pillow and numpy, and ffmpeg on the PATH for the video. In the prompts, `<WORK_DIR>`
stands for the folder the raw renders were saved to.

1. **Pictures**: Codex CLI's built-in image generation (`codex exec` with `gpt-6.1-sol`, reasoning
   medium), each prompt file fed on stdin and the reference images attached with `-i`:
   - `candidates.txt` drew three candidates; the third was picked.
   - `main.txt` and `moods.txt` drew the main picture and a 2x2 mood sheet, with the picked candidate
     (for the moods: the main picture) as the character reference.

   Every prompt also attached a style reference: an anime illustration with a light pixel-art finish
   that the owner supplied. It is not included here, and the prompts ask for its style only, not its
   character, outfit or pose. Everything is drawn on flat `#00FF00`, because the generator paints a
   checkerboard when asked for transparency.
2. **Animation**: Grok CLI's `image_to_video` (720p, 6 seconds, 24 frames a second) animated the main
   picture with `grok_idle.txt`. Frame 136 nearly matches frame 0, so the loop is cut there and needs no
   crossfade. A crossfade put two hands in the picture.
3. **Keying**: `tools/key_green.py` takes the green out (the raw renders and the video are not kept: a
   rerun of the generators would draw something different anyway):

   ```
   python tools/key_green.py image main_raw.png art/source/mascot.png --max 384
   python tools/key_green.py image main_raw.png art/source/icon.png --crop 150,0,1010,860 --max 384
   python tools/key_green.py grid moods_raw.png art/source mood_ok mood_rerouted mood_idle mood_error --max 384
   python tools/key_green.py frames idle_raw.mp4 art/source/mascot_anim.webp 0 136
   ```
4. **Into the program**: `python tools/make_assets.py` embeds them in `codex_routing_assets.py`, writes
   `docs/icon.ico` and the copies in `docs/` and `design_handoff_routing_detector_ui/assets/`. Then
   `python tools/make_screenshots.py` and `python tools/make_social_preview.py` redraw the README
   screenshots and the social preview card.
