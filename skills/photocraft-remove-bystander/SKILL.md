---
name: photocraft-remove-bystander
description: Use when the user asks to remove a stranger, bystander, passer-by, tourist or other unwanted person from a photo with PhotoCraft (ArtCraft's pixel editor), including a LightCraft photo handed over as its -Edit.psd copy, e.g. "remove the person on the right", "get rid of the guy behind her", "erase the stranger near Sarah's arm", or runs /photocraft-remove-bystander.
---

# photocraft-remove-bystander

Remove a person from a photo in the control PhotoCraft, without touching the people who should stay,
and save it back. Tested November 2026 on PhotoCraft 0.23.1 with a LightCraft `-Edit.psd` (6000x4000,
16-bit, flat): a small, out-of-focus man standing behind the subject's arm, half hidden by her sleeve.

## 0. Set up

- **Which file, which person.** Get the path and where the bystander is ("right side, near Sarah's left
  arm"). For a LightCraft photo, the copy is `<name>-Edit.psd` next to the original, with its LightCraft
  id. Don't send the photo from LightCraft again if it already has a copy (it fails and leaves an
  `-Edit-2.psd`), see `photocraft-mcp` → Round trip with LightCraft.
- **Back up the file** before anything else (copy it to the scratch folder and compare hashes).
- **Start the control PhotoCraft with the photo's folder as both read and write root**, using the
  `photocraft-mcp` skill: `start -ReadRoot <folder> -WriteRoot <folder>`. A running one with other roots
  has to be stopped first, which closes its window. Ask before you do that.
- **Driving it.** Use the `mcp__photocraft__*` tools when they are loaded. When they aren't (the server
  was registered after the session started), use the plugin's driver, which runs one tool call after
  another and saves screenshots as PNG files you can look at:

  ```bash
  python "<base>/../../scripts/pc-bridge.py" calls.json
  ```

  `calls.json` is a list of `[tool, arguments]` pairs, such as
  `[["doc_open", {"path": "_X-Edit.psd"}], ["ui_screenshot", {}]]`. Write it with a short Python script
  rather than quoting JSON on a PowerShell command line (long nested JSON breaks there). It stops at the
  first error. Its exit codes: 0 every call succeeded, 1 a tool error, 9 PhotoCraft not found, 10 no
  usable token file, 11 a bad calls file or option.

## 1. Find the person, in document pixels

`doc_open path=<name>-Edit.psd`, then `ui_set fields={"zoom":<z>,"center":[x,y]}` and `ui_screenshot`.
In bridge mode `render_preview` is a window screenshot too, so there is no full-resolution export.

- **Screen to document.** At zoom `z` one document pixel is `z` screenshot pixels: the screenshot is
  already at the display's scale, so don't also multiply by `pixelsPerPoint`. Measure one known point
  (draw a selection with known corners and find its marching ants) and use
  `doc = known_doc + (screen - known_screen) / z`. Guessing the offset from the canvas centre was 50 px
  off.
- Zoom to 75–100 % on the person. Note the head, the torso, the legs and **the feet**, which are easy to
  cut off when the view ends above them. Scroll down (`center` lower) to see them.

## 2. Select the person, not the subject

1. **Make the photo layer active first**: `command_run id=layer.select params={"layer":<photo layer id>}`
   (from `doc_inspect`). `select.subject` samples the *active* layer: with a fill layer active it found the
   "subject" on that layer and nothing was subtracted.
2. Draw a polygon around the whole person with a margin of 15–30 px:
   `select.lasso {"polygonal":true,"points":[[x,y],…]}`. Where the person is behind the subject, run
   the polygon into the subject. The next step cuts it back.
3. `select.subject {"mode":"subtract"}` removes the subject (the person who stays) from the selection.
   Its result reports the subject's bounds, not the selection's. Look at the screenshot instead.
4. `select.modify.feather {"radius":1.5}`.
5. Screenshot and check that the marching ants go around head, body, legs and shoes, and follow the
   subject's edge where the two meet.

`select.object` with a rectangle around a small, blurry figure caught only the torso (no head, no legs).
Use the polygon.

## 3. Fill: clone from the same rows, not Content-Aware Fill

Paint on a new layer so a bad attempt is one `layer.delete` away: `layer.new.layer {"name":"Bystander
clone"}`, with the selection still active (strokes stay inside it).

**What worked:** `paint.cloneStamp` with a horizontal `offset` to the side where the background
continues, so every row is copied from the same row: hedge from hedge, path from path.

```json
{"id":"paint.cloneStamp","params":{"offset":[420,0],"sampleLayer":"all","size":110,"hardness":70,
 "points":[[x0,y],[x1,y],[x1,y+50],[x0,y+50],…]}}
```

- Make the offset larger than the person's width, so no source pixel is part of the person.
- Zig-zag the points across the selection's bounding box (every 50 px for a 110 px brush), with a
  margin of 20–40 px.
- Where the copied rows don't fit (a light sky band above the head copied as dark trees), select that
  band (the same polygon, minus the subject, `select.rect … "mode":"intersect","feather":25`) and clone it
  again from just above (`"offset":[0,-175]`, `sampleLayer:"all"`, softer brush), so the sources lie
  outside the person.

**What didn't work** (on this photo):
- `edit.contentAwareFill` with `sampling:"auto"` or with `samplingStrokes`: it left a pale grey-lilac
  haze along the subject's sleeve and a hard seam on the selection's right edge. A sampling stroke along
  the path below pulled path texture into the greenery. `colorAdaptation:"none"` didn't help. Splitting
  it into an upper and a lower fill gave flat bright greenery with a hard edge.
- If you do try it, use `output:"new"` (it returns the new `layer`) so you can delete it.

## 4. Clean up

1. `layer.mergeDown {"layer":<clone layer>}` so the healing tools see one layer.
2. **Leftovers the subject mask kept.** The subject mask can claim part of the bystander that touches
   the subject (here a bit of his jeans under her cuff). Select it with a polygon whose edge follows the
   subject's outline, 2 px outside it, then `paint.remove` with a closed stroke inside it
   (`size` 60, `hardness` 50), and `select.deselect`.
3. **Seams.** `paint.spotHealing {"type":"contentAware","size":36,"hardness":30,"points":[…]}` along each
   edge of the cloned patch that lies on background, every 10–20 px. Keep these strokes off the subject.
4. Check at 200 % on the edges, then at 50 % and at the whole-photo view (`zoom` 0.2 for 6000 px). Look
   for haze, repeated texture, cut-off feet and leftover colours (blue jeans, a shoe).

Every step is in History. `edit.undo` or `layer.delete` reverses one.

## 5. Save and hand back

1. Flat is what LightCraft has been tested with: after `layer.mergeDown` there is one layer; otherwise
   `layer.flattenImage`.
2. `doc_save path=<name>-Edit.psd` (the same name, in place) and `ui_menu_invoke id=file.close`. The 144
   MB file became 290 MB (RLE plus a layer block), as `photocraft-mcp` describes.
3. LightCraft reloads the copy: `photo.reload ids=[<copy id>] wait=true`, run from the LightCraft
   session, or with
   `"<LightCraft dir>/lightcraft-cli.exe" run --connect 127.0.0.1:7980 photo.reload ids=[<id>] wait=true`
   (it returned `{"reloaded":[<id>]}` in 0.3 s). If another session drives LightCraft, tell it the file
   is saved instead of reloading behind its back.
4. Keep the backup until the user has seen the result. Delete it only when they agree.

## Common mistakes

- `select.subject` with the wrong layer active (step 2.1).
- Converting screen to document coordinates with `pixelsPerPoint` (step 1).
- A selection that stops above the feet.
- Filling with Content-Aware Fill next to the subject (step 3).
- Saving from a regular PhotoCraft that LightCraft's send opened: the bridge can't drive it, and two
  editors on one file overwrite each other. Leave it alone, and tell the user it holds an old copy.
- A tool call sent before the reply to the one it depends on (open → select → fill → save) can finish
  out of order. `pc-bridge.py` waits for each reply.
