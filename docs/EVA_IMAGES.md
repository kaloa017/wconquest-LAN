# Preparing EVA JPG images

EVA-00, EVA-01 and EVA-02 are separate country wonders, hidden until a player owns
Japanese territory. Each unlocks only its corresponding portraits. They never
change combat, movement, income or other statistics. No artwork is bundled.

1. Choose artwork you have permission to use. Crop a portrait to **512 × 768 px**,
   or **512 × 512 px** for a square image.
2. Export as a real **JPEG**, RGB, quality 80–85. Aim for **100–300 KB** and stay
   below **1 MB** per file. Flatten the background; changing a PNG extension is not conversion.
3. Put images in `static/eva/` beside the game's Python files.
4. Use lowercase names: `eva_00.jpg`, `eva_01.jpg`, `eva_02.jpg`. Variants can be
   `eva_00_blue.jpg`, `eva_01_night.jpg`, `eva_02-red.jpg`. The `eva_00`, `eva_01`
   or `eva_02` prefix assigns the required wonder. Hyphen equivalents such as
   `eva-01.jpg` work too. Only lowercase letters, digits, underscores/hyphens and
   `.jpg` are accepted. Older unclassified JPG filenames use the EVA-01 unlock.
5. Start the server and claim Japanese territory. In **Country → Wonders**, purchase
   the desired EVA wonder; no specific tile or selected tile is required to buy it.
   For a separate test server, use a copy of your save and the host resource tools.
6. Reopen Country. The gallery shows portraits for wonders you own. Check each
   type separately: owning EVA-00 must not reveal/deploy an EVA-02 portrait.
   Select an owned tile, then use **Place on selected owned tile**. The portrait
   appears on the map; placing another replaces it. Each player has one cosmetic
   portrait displayed at a time. Check on a phone and verify stats stay unchanged.
7. To replace artwork, overwrite the same JPG and reload with Ctrl+F5. To add a
   variant, add another correctly prefixed filename. Reopening Country scans the
   directory without a server restart. The gallery shows at most 24 unlocked images.

Open `/static/eva/eva_01.jpg` to troubleshoot an image URL. Check the actual JPEG
format, file size, prefix and matching wonder ownership if placement fails. Static
artwork is public, even though gallery/placement access requires the relevant
unlock; do not store secrets here.

Previous Geofront owners receive all three wonders automatically, keeping their
unlock and existing deployment. `.gitignore` excludes local EVA JPGs and an
`EVA_IMAGES` folder while tracking this guide. Keep artwork backed up separately.
