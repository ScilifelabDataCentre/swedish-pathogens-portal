# Official EU icons for AI-generated content

This directory holds the European Commission icon pack for labelling
AI-generated content. The filenames here are normalized. The file bytes are
the Commission originals, downloaded on 29 September 2026. The icons were
published with the Code of Practice on 10 June 2026.

- Source page: https://digital-strategy.ec.europa.eu/en/policies/eu-icons-labelling-ai-generated-content
- SVG pack: https://ec.europa.eu/newsroom/dae/redirection/document/129546
- PNG pack: https://ec.europa.eu/newsroom/dae/redirection/document/129547

The Commission states that the icons are free to use and that attribution is
not required. Using them does not by itself show compliance with Article 50,
and it does not mean SciLifeLab has signed the Code of Practice.

## Which files are embedded

The labelling service embeds one opaque PNG into a confirmed picture-like
image:

| Editor choice | Icon |
|---|---|
| Fully AI-generated | `fully-ai-generated-black.png` or `fully-ai-generated-white.png` |
| Partially AI-modified | `partially-ai-modified-black.png` or `partially-ai-modified-white.png` |

Black or white is chosen from the average colour of the rectangle the icon
will cover. The service uses the variant with the higher WCAG contrast. When
the two ratios are equal, it uses black.

Pillow does not render SVG, so the SVG files are not drawn onto images. The
`-50` files are the Commission's transparent variants. The `basic-*` files are
the short icon from the same pack. Those files stay here so the downloaded
pack remains complete. Their checksums are listed below and checked by the
icon test. The labelling service does not embed them.

Still JPEG, PNG, and WebP images can be labelled. Animated images are left
unchanged.

## Placement profile `eu-2026-06-10-top-right-v1`

The Code of Practice does not set a pixel size. It gives the top-right corner
as the example placement and requires the icon to stay visible against its
background. This profile is the rule the portal uses:

- corner: top-right
- padding: 2% of the shorter side, and at least 4 pixels
- width: 22% of the image width, then reduced so the icon and its padding stay inside the image
- height: the same proportion as the official icon, then reduced in the same way
- minimum box: 16 pixels on both sides after padding; a smaller image is not labelled
- contrast: black or white, as described above

`label_version` on the disclosure stores this profile id. The service will not
place an icon on a file that was already labelled with a different profile,
because that public file already contains an icon. The copy from before
labelling is kept in the private archive. An editor who does not want the icon
deletes the image and uploads it again.

## SHA-256

These digests are the values in `OFFICIAL_ICON_SHA256`. Labelling stops if an
embedded PNG does not match.

### Embedded

| File | Original name in the Commission pack | SHA-256 |
|---|---|---|
| `fully-ai-generated-black.png` | `LABEL_AI GENERATED_black.png` | `8d0af57bc93ba3797042a4b56db757d85f924d9b0200b75b8842da7be5e402a2` |
| `fully-ai-generated-white.png` | `LABEL_AI GENERATED_white.png` | `f139d8de4b5173f47a777431e7e03d9258d8ea7ee1ee1a062febc7e9fff067fc` |
| `partially-ai-modified-black.png` | `LABEL_AI MODIFIED_black.png` | `0f32e4afbe1459baaf425c78373ea541421ecdb61803438892e2fc07df67da8f` |
| `partially-ai-modified-white.png` | `LABEL_AI MODIFIED_white.png` | `64241cf4f87eb0837bd234cb63716c7d78f4e9dbbb8866f40464ca4e6bfbfead` |

### Kept, not embedded

| File | Original name in the Commission pack | SHA-256 |
|---|---|---|
| `fully-ai-generated-black.svg` | `LABEL_AI GENERATED_black.svg` | `503af176b05fd725e68b0aa526977d31bcd657d74b15c6103a57ace81384940f` |
| `fully-ai-generated-black-50.svg` | `LABEL_AI GENERATED_black transparent.svg` | `63d28ab55916b4548edff21d5fbcac065a13e5fb936e9b304ff0bada45f2fac1` |
| `fully-ai-generated-white.svg` | `LABEL_AI GENERATED_white.svg` | `10125cdef3fc60a351df72fe1266bb00ea046086921bd1bb20135f0f07b5ed36` |
| `fully-ai-generated-white-50.svg` | `LABEL_AI GENERATED_white transparent.svg` | `d19736f6da9d38af3cffce8ba08f3f7658b573e1794c173fcd8b55a5c200ed44` |
| `partially-ai-modified-black.svg` | `LABEL_AI MODIFIED_black.svg` | `2e7349e5eca4ee78eeef160dfef4545c31850932245373a07c5401e73e6599c0` |
| `partially-ai-modified-black-50.svg` | `LABEL_AI MODIFIED_black transparent.svg` | `9ab09f54c1ccef01799af43794cd93a8af6607ba9ac6b9526fb90a02be8ddf3d` |
| `partially-ai-modified-white.svg` | `LABEL_AI MODIFIED_white.svg` | `0c72a7d569a1447e2982a843e156bd5f9cb2ab6f201943c6c68f988dc2f1bb6e` |
| `partially-ai-modified-white-50.svg` | `LABEL_AI MODIFIED_white transparent.svg` | `7ccbce41f9f821a574007b32806ddb6d635ee8bbc5d753ccd05f66f5a3165845` |
| `basic-black.svg` | `LABEL_AI_black.svg` | `58ffe859a4d74829d397f534a988081bcefb716849c7d3b84fa7a026dd1d257f` |
| `basic-black-50.svg` | `LABEL_AI_black transparent.svg` | `f8e20f1dde8c7d95940da08960b1063620812acc9b4ea96eb5ad051f80f67c21` |
| `basic-white.svg` | `LABEL_AI_white.svg` | `5b3b94ae67fea55c4f2d013d0b8ed5b876c1533555ed0ed60e688f2f3ccf1a50` |
| `basic-white-50.svg` | `LABEL_AI_white transparent.svg` | `52d87cb3f6a191dba24796f745e1eeb80d342883acd1a2e6d856342ad853766c` |
