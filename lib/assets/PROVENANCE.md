<!-- markdownlint-disable MD013 MD060 -->
# Provenance: BlackCat hero image

The files in this folder: `blackcat-hero-original.png` (the model's output, unmodified),
`blackcat-hero.jpg` (README hero), `blackcat-social-1280x640.jpg` (social preview) and
`blackcat-avatar-640.png` (avatar). Licence and attribution: [README.md](README.md) in this folder.
Hashes are SHA-256; times are Europe/Lisbon.

## 1. Decisions by the author (2026-10-03)

- Published variant: **B** (violet/turquoise/amber) of two generated variants.
- Licence: **CC BY 4.0** ([legal code](LICENSE-CC-BY-4.0.txt)). Attribution: Pedro Miguel Rodrigues Jorge.
- AI-edit disclosure: "Photo by the author, AI-edited with OpenAI GPT Image 2.5 Sunburst via Opper".

## 2. Source photograph (human-authored, not included)

- The author's own photograph (not included), SHA-256
  `c05d1d75a39c90e55760c3e4b3055955e6c979be7caa65a4e047ae15b121efa2`. Author: Pedro Miguel Rodrigues
  Jorge; subject: his own black cat.
- The model's reference was the photo region cut from it (689x362 px, ImageMagick `-crop`, pixels
  untouched; not included), SHA-256 `95297f01a81fbc958501400bd3114c6b948b6cf9d3acab98ae320f334dbcba50`.

## 3. Model

- Tool: the stack's image-studio MCP server, `generate_image`; model `openai/gpt-image-2.5-sunburst`
  (OpenAI GPT Image 2.5 Sunburst), provider Opper (as reported by the tool; no further snapshot id returned).
- Reference: the crop of §2 (image 1). Settings: size 2048x2048, quality high, PNG, one image per call.

| Variant | Job id | Request time | Output SHA-256 | Cost (USD) | Published |
|---|---|---|---|---|---|
| A terracotta/cream + teal | gen_034zziwRJN9k9Kq3D3YQSS | 2026-10-03T16:15:18+01:00 | `d2a302284d0c7ecdf159f6c90e2ec775a2dd1d22957d8249d94ce0b212eeba8b` | 0.113217 | no |
| B violet/turquoise/amber | gen_034zzk2bbrrciKK0YV3Enh | 2026-10-03T16:16:17+01:00 | `cc7e566f2529343fa4bc10f8dd988c15b74dad40a956e93e3cbdf3cbd0835663` | 0.113282 | yes: `blackcat-hero-original.png` |

### Prompt A (verbatim)

```text
Image 1 is a photo of my own black cat: keep this exact cat and pose. An all-black short-haired cat with a slim body, large pointed ears and a long thin tail, seen from slightly above and side-on facing right, sitting with its head bowed, licking its raised front paw (small pink tongue, grey paw pads visible, white whiskers), the tail stretched straight out to the left along the ground. Exactly one cat, four legs, one tail, two ears, natural anatomy.

The cat is a calm giant sitting in the middle of a bright miniature toy city of code, seen as a slightly isometric tabletop diorama: glossy little building blocks and tiles forming streets and terraces; tiny cute generic robots (round and boxy bodies, antennae, glowing visor eyes, no markings) carrying and stacking blocks; miniature terminal windows showing only abstract coloured bars; floating curly-brace, bracket and angle-bracket shapes; a small branching graph of glowing lines; circuit-board paths; folder and file tiles; small checkmark and gear tiles; tiny pipes linking the robots. All details are small and surround the cat and its tail.

Palette A: warm terracotta #C8643C, coral #E8836B, amber #F2A541 and cream #F6E9D7 dominant, with teal #1FA5A0 accents. Warm rim light and a soft glow outline the black fur so it reads clearly against the bright ground; soft shadows, shallow depth of field, crisp clean toy-diorama render, square composition with the cat centred.

No text, no letters, no numbers, no logos, no star or sparkle symbols, no watermarks, no people, no other cats.
```

### Prompt B (verbatim; identical to A except the palette paragraph)

```text
Palette B, vivid and high-contrast: electric violet #7B4DFF, turquoise #22D3C5 and teal #0E9F9A with glowing amber #FFB238, plus touches of coral #F07858 and cream #FFF1DC. Neon-tinted rim light and a soft glow outline the black fur so it reads clearly against the bright ground; soft shadows, shallow depth of field, crisp clean toy-diorama render, square composition with the cat centred.
```

## 4. Metadata of the unmodified output

- PNG, 2048x2048, 8-bit TrueColor sRGB, gAMA 0.4545; no EXIF/XMP text chunks.
- A `caBX` chunk with a C2PA JUMBF manifest (spec 2.2.0, `c2pa.actions.v2` with `c2pa.created`,
  digitalSourceType `trainedAlgorithmicMedia`), signed for "OpenAI Media Service API" (OpenAI OpCo, LLC;
  Trufo C2PA Claim Signing CA; OpenAI TSA timestamp). Checked with `magick identify -verbose` and a byte
  search; the signature was not cryptographically validated (unverified).
- An invisible SynthID watermark may be present (cannot be checked locally). Nothing was done to strip or
  bypass either; `blackcat-hero-original.png` is published byte for byte as the model returned it.

## 5. Published files (ImageMagick only, Lanczos; no model calls)

| File | Operation | SHA-256 |
|---|---|---|
| `blackcat-hero-original.png` (2048x2048, 5,178,979 B) | byte-identical copy of the variant B output; keeps the C2PA manifest | `cc7e566f2529343fa4bc10f8dd988c15b74dad40a956e93e3cbdf3cbd0835663` |
| `blackcat-hero.jpg` (1600x1600, sRGB, q90, 527,692 B) | resize | `dd2cd35afdc061b7d0c57aaf68f838e295e19d5d6796e0682e9a72c257de0f69` |
| `blackcat-social-1280x640.jpg` (q88, 191,758 B) | 2:1 crop 2048x1024+0+430, resize | `e5dfc4a305d64f96c2422ee18335c88c106a008d7d6a23b159bf1a644a73364d` |
| `blackcat-avatar-640.png` (640x640, 569,170 B) | crop 1000x1000+960+400 (head and upper body), resize | `fdbfa301a409253e8595fae3c0461a839c9bba1ad649b71892fa983e68579f15` |

The three resized copies were re-encoded, so they carry no C2PA manifest (it is bound to the original
file's bytes); `blackcat-hero-original.png` keeps it, which is why it is published next to them.

## 6. Who did what

- Human (Pedro Miguel Rodrigues Jorge): the photograph of his cat; the direction; the choice of variant B
  and of the crops.
- AI (`openai/gpt-image-2.5-sunburst` through Opper): the toy-diorama scene and the rendering of the cat
  into it from the photograph.

## 7. Licensing notes (research summary, 2026-10-03; not legal advice)

1. The model maker's output terms give the output to OpenAI's customer (here Opper):
   [OpenAI Services Agreement](https://cdn.openai.com/osa/openai-services-agreement.pdf) §4.1.
2. Opper's terms cover only its users' data; nothing found passes the output rights on to them, so who
   holds those rights is unclear: [Opper terms of service](https://opper.ai/terms-of-service) §8.2.
3. Nothing found limits licensing or redistributing the outputs.
4. API images carry C2PA metadata and an invisible SynthID watermark; do not strip or bypass them
   ([OpenAI help](https://help.openai.com/en/articles/8912793)). The original is published unmodified.
5. CC BY 4.0 §2(b)(2) leaves trademark rights out of the licence.
6. EU AI Act Art. 50: nothing mandatory for the author; the README's caption is a voluntary disclosure.
7. No Anthropic logo, starburst/sparkle mark, mascot or the word "Claude" appears: Anthropic's
   [trademark guidelines](https://www.anthropic.com/legal/trademark-guidelines) forbid them without written
   permission (the prompts forbade text, logos and star/sparkle symbols).
8. No people or likenesses appear in the image.
9. Purely AI-generated material may not be copyrightable (the [US Copyright Office](https://www.copyright.gov/ai/)
   holds that copyright does not extend to it), so CC BY 4.0 applies to the extent rights exist: the
   author's photograph and his creative choices.
