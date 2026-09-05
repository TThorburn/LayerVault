# Third-party notices

LayerVault uses or redistributes the following open-source components and data.

LayerVault itself is licensed under GNU AGPL-3.0-only. The complete licence is included in the repository and release root as `LICENSE`. The notices below describe separately copyrighted components and data retained by the distribution.

## three.js 0.185.1

Copyright © 2010–2026 three.js authors. Licensed under the MIT License. The licence text is included at `third_party/three-LICENSE.txt`.

## Manifold 3D 3.5.1

Licensed under the Apache License, Version 2.0. The licence text is included at `third_party/manifold-3d-LICENSE.txt`.

## SketchForge 3D 1.0.7

SketchForge is the local-first browser CAD editor created by Formsmith746 and contributors. LayerVault embeds the official Next.js application in **Workshop** without VNC and adds a local model-library handoff.

Upstream: https://github.com/Formsmith746/SketchForge-3D

SketchForge is licensed under GNU AGPL-3.0-only. Its corresponding source and upstream licence are included at `third_party/sketchforge/`.

## OrcaSlicer printer profiles and artwork

LayerVault redistributes the machine-profile JSON and printer cover images from OrcaSlicer's open printer profile library. These files populate matching FDM printers in **Printers & Profiles**. LayerVault does not bundle or run the OrcaSlicer application.

Upstream: https://github.com/OrcaSlicer/OrcaSlicer

OrcaSlicer is licensed under GNU AGPL-3.0. The retained data and licence are included at `third_party/printer-artwork/orcaslicer/`.

## DragonFruit printer plugin artwork

LayerVault retains printer presets and artwork from the Anycubic, Elegoo, and Athena DragonFruit plugin packs to populate matching resin printers. LayerVault does not bundle or run the DragonFruit slicer application.

Upstream: https://github.com/Open-Resin-Alliance/DragonFruit

The retained Open Resin Alliance printer plugin packs are MIT-licensed. Their source data, artwork, and individual licence files are included under `third_party/dragonfruit/plugins/`.

## UVtools printer catalogue data

LayerVault retains the small PrusaSlicer-compatible printer-profile dataset maintained by the UVtools project so resin-machine specifications work offline. The UVtools application and noVNC runtime are not bundled or launched.

Upstream: https://github.com/sn4k3/UVtools

UVtools is licensed under GNU AGPL-3.0-or-later. Retained profiles and upstream responses keep their source and licence attribution in LayerVault's printer catalogue.

## Supplemental printer product artwork

For retired machines not covered by the open printer libraries, LayerVault links exact-model product artwork from the manufacturer or a named product/reference page. One NOVA3D Elfin2 catalogue thumbnail is cropped from the product image on the Elfin2 user-manual cover and retained locally so the discontinued model remains recognizable offline. Each affected catalogue record links its source page; this artwork is descriptive product identification and is not represented as open-source.

The EPAX, Longer, Phrozen and Qidi coverage uses live manufacturer imagery where available and exact-model archival product pages for discontinued hardware. Remote images are allow-listed, validated as image responses, cached locally at first use, and retain their source-page attribution. They are not bundled into the release archive or represented as freely redistributable assets.
