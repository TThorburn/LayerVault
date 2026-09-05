# LayerVault integration notice

SketchForge is developed by Formsmith746 and the SketchForge contributors:

- Project: https://github.com/Formsmith746/SketchForge-3D
- Source snapshot supplied for this integration: 1.0.7 (`main` archive)
- Licence: GNU Affero General Public License v3.0 only
- Full licence text: `LICENSE`

LayerVault runs the official Next.js application as a separate Docker service
and embeds that web interface in its existing **Workshop** destination. It does
not use VNC or a streamed desktop.

## LayerVault-specific addition

`apps/web/src/app/page.tsx` contains a small, origin-checked `postMessage`
receiver. It accepts a user-selected STL, OBJ or STEP file from the LayerVault
parent frame and passes it through SketchForge's normal import/project creation
path. The receiver is enabled only when LayerVault supplies the exact parent
origin in the editor URL.

SketchForge's private projects remain in that browser's local storage. Projects
explicitly saved to SketchForge's Docker **Shared** space are stored under
LayerVault's `data/sketchforge/projects` directory and included with the
LayerVault **Projects & Workshop designs** backup scope.
