<!-- markdownlint-disable MD013 MD060 -->
# Provenance: BlackCat hero image

The files in this folder: `blackcat-hero.jpg` (README hero), `blackcat-social-1280x640.jpg` (social
preview) and `blackcat-avatar-640.png` (avatar). Rights and restrictions: [README.md](README.md) in this
folder. Hashes are SHA-256.

## 1. The author's photograph (human-authored, not included)

- The author's own photograph of his black cat (Pedro Miguel Rodrigues Jorge), 900x1600 JPEG,
  SHA-256 `4c682759d818a97988cd9a4de54b349da9866afe401261d921bf1af7544fb288`. Not published.
- No EXIF metadata in the file (no capture date, camera or location recorded).
- A crop of it (600x340 px, SHA-256 `2ec32d48f46e411ab94d1123c7952a464c9abd2654138212651346573def91d6`)
  was sent as a second identity reference. Not published.

## 2. Earlier AI image (base scene)

- 2048x2048 PNG, SHA-256 `0d783e95ca97288020a8d8fe7b7d5a3bbe3716232caa4e92501d171184baae78`. Not published.
- Origin, as stated by the author (not independently verified): generated through Opper with
  `openai/gpt-image-2.5-sunburst`, under the author's direction. Prompt and date not recorded.

## 3. Edit (2026-10-03, Europe/Lisbon)

- Model: Sourceful Riverflow v2.5 Pro (`sourceful/riverflow-v2.5-pro`) through OpenRouter, called from
  the stack's image-studio MCP server (`edit_image`), which scales local inputs under 1920 px first.
- Inputs, in order: the earlier AI image (§2), the photograph (§1), its crop.
- Settings: aspect ratio `1:1`, resolution `4K`, output PNG; the model has no seed parameter.
- Output: 2880x2880 PNG, SHA-256 `99455317a8f79a41bfaadb00f452d8285e159b1d806d99f29c6fa941d21797ea`
  (variant B of two; the other variant was not used). Not published.
- Prompt (verbatim):

> Edit image 1 and change only the cat. Images 2 and 3 show the owner's own cat (image 3 is a close crop of image 2); the cat in image 1 must become this exact cat, recognisable as the same individual. Match it closely: pure jet-black short, smooth coat lying flat to the body; tall, upright, pointed ears that are large for the head; a lean angular face with a narrow muzzle and white whiskers; a slim, light-boned body with long slender legs; and a long, thin tail, much thinner than the fluffy tail in image 1, tapering to a fine tip. The cat keeps the mid-leap pose over the car roof from image 1, same place in the frame, same size, front paws reaching forward, tail streaming back. Under the low golden-hour sun the black fur shows a natural glossy sheen with warm highlights along the back and ears. Everything except the cat stays exactly as in image 1: the dark grand-tourer and its reflections, the villa entrance, the cypress and olive trees, the terracotta pots, the cobbled drive, the hills and sky, the shallow depth of field and the square composition. Photorealistic, no text, no logo, no watermark, no extra limbs.

## 4. Metadata and watermarks

The model's output (§3) carries no provider metadata: its only chunks besides the image data are
`IHDR` and `pHYs` (no `tEXt`/`iTXt`/`zTXt`, `eXIf`, XMP or C2PA content credentials), and no visible
watermark. The published derivatives were made with `-strip`, which therefore removed nothing the
provider generated; they carry a bare JFIF header (JPEG) or no ancillary chunks (PNG), so no EXIF and
no location data.

## 5. Derivatives (ImageMagick, no model)

From the output of §3 (`S`):

| File | Command | SHA-256 |
|---|---|---|
| `blackcat-hero.jpg` (1600x1600) | `magick S -colorspace sRGB -resize 1600x1600 -strip -sampling-factor 4:4:4 -quality 90` | `200c21ac488cc190b2d546f5f098a3fff0595a678ebeb89e6636e11b666c7534` |
| `blackcat-social-1280x640.jpg` | `magick S -crop 2880x1440+0+200 +repage -resize 1280x640! -strip -quality 88` | `3c3b8adb86e975e4a75c0663b9bb9a0639e06bf2ff61dcc71f4c260141a5d8bd` |
| `blackcat-avatar-640.png` | `magick S -crop 1300x1300+585+0 +repage -resize 640x640 -strip` | `6a065cf928c6f38d6e9e5f470b3a3c28efe0e9706486164f593c65b7db72a448` |

## 6. Who did what

- Human (Pedro Miguel Rodrigues Jorge): the photograph of the cat; the direction of the earlier AI
  image (per the author); the choice to base the hero on the photograph; the final selection.
- AI: the earlier scene (`openai/gpt-image-2.5-sunburst`, per the author); the re-rendering of the cat
  into that scene from the photograph (`sourceful/riverflow-v2.5-pro`). The cat's pose, the scene, the
  light and the eyes (yellow; not visible in the photograph) are model output, not from the photograph.
