# Changelog

## 0.3.29 — New Project Identity

- Replaced the original cube glyph with a purpose-made layered-vault brand mark.
- Added transparent master, 512 px, 192 px and 64 px image assets.
- Added a browser favicon and Apple touch icon.
- Included the new identity in the Docker image and self-hosted release archive.

## 0.3.28 — Self-hosted Release Polish

- Standardised the project, release archive and extracted directory name as **LayerVault** / `layervault-suite`.
- Licensed LayerVault under GNU Affero General Public License v3.0-only and included the complete licence in the release root.
- Documented the trusted-LAN deployment model and the roles of ports 8088 and 3004, including the scope of optional basic authentication.
- Retained the complete printer-artwork coverage and user-photo priority from v0.3.27.

## 0.3.27 — Complete Brand Artwork Pass

- Added verified exact-model or same-chassis product artwork for all visible EPAX, Longer, Phrozen and Qidi catalogue results.
- Retained the complete Nova3D, Wanhao, Prusa SL1/SL1S SPEED, Elegoo Mars/Saturn, legacy Creality HALOT/LD and Snapmaker artwork coverage.
- Hid UVtools' unverified `Phrozen Shuffle 16` software preset instead of attaching a misleading photo from a different large-format Phrozen printer.
- Kept OrcaSlicer's internal `fdm_*` inheritance templates hidden so searches contain only real printer variants with their existing cover images.
- Kept existing user-uploaded printer photos ahead of catalogue artwork.

## 0.3.25 — Catalogue Identity & Artwork

- Removed OpenPrintTag from the material catalogue and detached its badges from previously imported local rows without deleting user inventory.
- Added explicit printer-family aliases and merged cross-source duplicates while retaining the matching image and filling missing machine specifications.
- Switched UVtools printer indexing to the retained offline profile subset and expanded exact image matching through DragonFruit and official manufacturer pages.
- Added exact product artwork sources for selected Phrozen, Creality, ELEGOO and UniFormation machines.
- Replaced misleading generic colour-variant filament photos with colour-accurate generated spool graphics until an exact user photo is supplied.

## 0.3.24 — Catalogue Photo & Import Polish

- Added explicit material-photo preview and replacement controls to the resin/filament editor.
- Added an editable library name for every file in the model-upload dialog while preserving original filenames.
- Expanded exact-product official artwork matching for major resin and filament manufacturers.
- Backfilled eligible existing material records at startup and retained user photos as the highest-priority image.
- Corrected broad product matching so unrelated Standard Resin artwork is never reused for a different resin family.

## 0.3.23 — Consolidated Printer Data & Material Artwork

- Merged duplicate printer-catalogue records across DragonFruit, UVtools and Orca by normalized manufacturer/model identity.
- Preserved the image-bearing printer record while filling missing dimensions and capabilities from its duplicate source.
- Added locally cached official product artwork for popular Anycubic, ELEGOO and SUNLU resins and Anycubic, Bambu Lab, Prusament and Deeplee filaments.
- Kept the recorded material colour as a separate visible swatch even when bottle/spool artwork is available.
- Added normalized material specifications including temperature ranges, density, diameter/tolerance, package weight, drying, speed, wavelength and exposure guidance when the selected source provides them.
- Kept Filament Cheat Sheet and FilamentDB as linked research references only; their datasets are not copied or redistributed without a suitable licence/API agreement.

## 0.3.21 — Reliable Uploads, Interactive FDM Plate & Resin Printer Artwork

- Fixed model imports when temporary uploads and model originals live on different Docker volumes, host disks or NAS mounts. Cross-device moves now copy safely instead of returning HTTP 500.
- Added a focused regression using the reported `obj_2_single_color (12)_stl_A.stl` filename and independent database/model-storage roots.
- Replaced the flat FDM plate overview with a real browser-rendered 3D build plate using stored STL, OBJ and 3MF geometry.
- Added orbit, pan, zoom, top and fit views, model copy placement, lighting and a millimetre grid while retaining OrcaSlicer as the authoritative arrangement and slicing engine.
- Added the bundled DragonFruit Anycubic, Elegoo and Athena resin-printer presets as an offline hardware source, including their MIT-licensed printer artwork.
- Matching resin printers already in **My printers & profiles** now receive the relevant DragonFruit machine artwork automatically unless the user supplied a custom photo.
- Preserved visible Open Resin Alliance/DragonFruit attribution and source licensing in the printer catalogue and third-party notices.

## 0.3.20 — Browser-native OrcaSlicer Integration

- Replaced the unreliable OrcaSlicer noVNC desktop with a fully themed LayerVault FDM workspace; there is no visible remote desktop, VNC server, window manager or websockify bridge.
- Added multi-model plate selection with individual copy counts, a browser plate overview, remembered upstream printer/process/filament profiles and common job overrides.
- Added a private headless API around OrcaSlicer's real CLI action mode, including input/profile validation, isolated asynchronous jobs, status polling, failure details and G-code downloads.
- Kept LayerVault model mounts read-only and generated G-code/logs inside the configured OrcaSlicer workspace.
- Removed the desktop locale path that produced the `en_US` switching dialog and subsequent noVNC disconnect.
- Added persistent BuildKit caches for OrcaSlicer's dependency and application object trees, allowing interrupted builds to resume instead of restarting their longest step.
- Increased the default OrcaSlicer compiler parallelism from one to four jobs, retaining the `ORCA_BUILD_JOBS` override for smaller and larger Docker hosts.
- Added concise 30-second build heartbeats so progress remains visible without Docker Desktop clipping multi-megabyte native compiler logs.
- Added focused failure output that exposes the final 250 native build lines when OrcaSlicer genuinely fails.
- Copies the completed package out of the application cache before the runtime image is assembled, preserving a clean and reproducible final image.

## 0.3.18 — Flexible Storage & First-run Reliability

- Added independent host bind mounts for the application workspace, SQLite database, original model files and backup archives.
- Added a polished **Storage locations** settings panel with live mount readiness, local/NAS examples and a downloadable Docker `.env` configuration.
- Preserved existing installations by retaining `./data`, `./data/files` and `./data/backups` as the defaults.
- Passed an external model mount through to UVtools and OrcaSlicer read-only so NAS-hosted originals remain available to both tools.
- Added Ocean, Orchid and Forest themes while preserving the translucent glass surface system and existing Frost, Midnight, Aurora and Sunset themes.
- Made the large OrcaSlicer build default to one compile job, with an `ORCA_BUILD_JOBS` override for well-provisioned systems.
- Confirmed the supplied `systemd-network`/`systemd-journal` messages are non-fatal dependency-install warnings; the provided log was clipped while GMP was still compiling and contained no actual error.
- Added external-path, Compose-mount, theme, API and memory-safe Orca build regression coverage.

## 0.3.17 — Original OrcaSlicer Desktop Workspace (superseded in 0.3.20)

- Added a dedicated, full-height **FDM Slicer** destination containing the complete OrcaSlicer 2.5.0-dev native application.
- Built OrcaSlicer from the supplied corresponding source with its supported Ubuntu build sequence rather than substituting a reduced slicer implementation.
- Added connection, source/credit, reload and full-screen controls in LayerVault's glass interface.
- Mounted LayerVault model storage read-only at `/layervault-data` and provided persistent `/workspace` projects/exports plus `/config` profiles and preferences.
- Included OrcaSlicer configuration in the **Printers & profiles** backup scope and its writable workspace in **Projects & Workshop designs**.
- Added visible OrcaSlicer contributor credit, an upstream source link and AGPL-3.0 identification.
- Included the complete supplied OrcaSlicer source, licence, native build recipe and integration notes under `third_party/orcaslicer`.
- Added service, source-completeness, persistence, backup and UI contract coverage.

## 0.3.16 — SketchForge Workshop

- Replaced LayerVault's original Workshop CAD implementation with the complete SketchForge 3D 1.0.7 browser editor.
- Runs SketchForge as a native Next.js companion service on port 3004; there is no streamed desktop, VNC layer or remote cursor.
- Added a searchable LayerVault model picker that transfers STL, OBJ and STEP files directly into a new SketchForge project without changing the stored original.
- Added connection, source/credit and full-screen controls in a compact glass header while giving the editor the rest of the viewport.
- Persisted SketchForge Shared projects under `data/sketchforge/projects` and included them in LayerVault's Projects backup scope.
- Added visible credit for Formsmith746 and contributors, an upstream source link and AGPL-3.0-only identification.
- Included complete corresponding SketchForge source, licence and LayerVault integration notes under `third_party/sketchforge`.
- Added integration, source-completeness, Compose, backup and UI contract coverage, plus upstream typecheck, unit-test and production-build verification.

## 0.3.15 — UVtools Native Workspace

- Integrated the complete native UVtools 6.2.1 application in a dedicated, full-height **UVtools** tab.
- Added file analysis, calibration, repair, conversion and manipulation through the official Avalonia UI rather than a reduced browser imitation.
- Added a self-contained .NET 10 container build and local X11/noVNC presentation service on port 3006.
- Mounted LayerVault data read-only at `/layervault-data` and provided persistent writable `/workspace` and `/config` locations.
- Added visible creator credit for Tiago Conceição (`sn4k3`), an upstream source link and AGPL-3.0-or-later identification.
- Added connection, reload, full-screen and first-start guidance while retaining LayerVault's glass interface around the native workspace.
- Included complete corresponding UVtools source and LayerVault integration notes under `third_party/uvtools`.
- Added integration, Compose, source-completeness, version, licence and UI contract coverage.

## 0.3.14 — DragonFruit SLA Slicer

- Integrated DragonFruit by Open Resin Alliance as a dedicated, full-height **SLA Slicer** tab.
- Added guarded PowerShell and Bash updaters for stable DragonFruit tags, with integration compatibility checks, pre-install container builds and automatic rollback preservation.
- Added a container-hosted bridge to DragonFruit's native Rust CLI so the integrated browser workspace can produce real resin slice files.
- Bundled the official Anycubic, CTB, Elegoo, SDCP v3, Siraya Tech and LYS-import plugins with their source and licences.
- Added explicit upstream credit, AGPL-3.0-or-later identification, beta validation guidance, connection status, reload and full-screen controls.
- Extended the normal Docker Compose stack with an independently health-checked DragonFruit service on port 3005.
- Removed the fixed LayerVault container name so parallel/rebuilt Compose projects no longer collide with an older container of the same name.
- Included complete corresponding DragonFruit source and LayerVault integration notes under `third_party/dragonfruit`.

## 0.3.13 — Resin Discovery & Glass Themes

- Added an offline-safe manufacturer resin index with 137 product families across 11 major brands.
- Added Anycubic, ELEGOO, Phrozen, Siraya Tech, SUNLU, eSUN, Formlabs, Liqcreate, AmeraLabs, RESIONE and Creality product discovery without requiring a selected printer.
- Kept Open Resin Alliance as the separate printer-specific exposure-profile source and clarified the distinction in the material catalogue.
- Preserved official catalogue links and reviewed source snapshots on imported resin stock.
- Added Frost, Midnight, Aurora and Sunset appearance choices to Settings with instant, browser-local persistence.
- Added a complete glass-style dark shell and theme-aware forms, cards, dialogs, navigation and Print Lab controls.
- Added provider/import, theme persistence and UI contract coverage.

## 0.3.12 — Multi-Model Print Lab

- Replaced Print Lab's single-model dropdown with a searchable multi-model tick-list and per-model quantity steppers.
- Added the normalized `job_models` manifest so creation, editing, repeats, history cards and CSV export retain every model and quantity.
- Made completed print counts reconcile by quantity across every linked model, including later edits and deletion.
- Corrected Anycubic PM3 header interpretation for XY pixel pitch, bottom exposure/layers, transition layers and lift/retract motion.
- Expanded editable/importable resin and FDM recipes with first-layer, speed, acceleration, shell, extrusion, support, brim, skirt and volumetric fields.
- Restyled Print Lab search and filter controls and fixed checkbox/quantity overflow in the full-height modal.
- Added dedicated multi-model persistence/count regressions and extended the slicer and UI contracts.

## 0.3.11 — Slicer-Aware Print Estimates

- Added bounded Anycubic PM3 named-table parsing for resin volume, print time, machine identity and core exposure settings.
- Recognised PM3 as Resin and switched the job form to the Resin recipe editor instead of the previous FDM fallback.
- Added Bambu/Orca G-code 3MF XML/JSON parsing for exact `used_m`, `used_g`, prediction time, printer, filament and settings metadata.
- Added automatic technology-compatible printer, material and profile matching, preferring embedded names and active/non-empty inventory.
- Prevented absent estimates from coercing to `0` in the browser.
- Read both the head and tail of large embedded G-code members while keeping archive inspection bounded.
- Added exact supplied-file regression coverage for the 65.234 ml PM3 and 53.38 g G-code 3MF, including saved-job values and the packaged artifact.

## 0.3.10 — Full-Height Application Shell

- Removed the shared page title/subtitle banner from every LayerVault destination.
- Reduced standard content insets so each page begins directly below the viewport edge rather than below an empty shell region.
- Expanded Workshop to use the complete desktop viewport height between compact top and bottom margins.
- Removed the old banner allowance from the Workshop height calculation so the CAD workplane receives the reclaimed space.
- Kept narrow-screen navigation accessible through a floating menu control and returned responsive Workshop layouts to normal document flow.
- Added UI contracts and live-browser coverage for banner removal, full-height CAD layout and responsive navigation.

## 0.3.9 — Priority & Print-File Workflow

- Replaced Workshop's library dropdown and the Project editor model dropdown with searchable, thumbnail-backed library pickers.
- Removed the repeated page-header model import action; Dashboard and Model Library remain the two intentional import entry points.
- Added independent 1–5 urgency and importance ratings to each project-model link, a visible combined score and priority-first ordering.
- Added streamed G-code, BGCODE, 3MF and PM3 inspection while creating a Print Lab record.
- Added slicer detection, material length/volume/weight extraction, duration parsing and recognised recipe-parameter import with manual overrides preserved.
- Calculated filament volume from length/diameter and weight from density when the source file omits those derived values.
- Retained the original sliced file on the job, exposed it for download, covered it in Print Logs backups and removed it with the job.
- Added fresh-schema, migration, API, attachment lifecycle, archive, UI-contract and exact-package regressions for the complete workflow.

## 0.3.8 — Settings & Backup Polish

- Removed the repeated `Backup DB` action from every page header.
- Added a dedicated Settings destination beneath Print Lab with a clear cog icon and calmer page-shell layout.
- Replaced database-only copies with self-describing ZIP archives containing a manifest, selected JSON exports, model files, custom images, result photos and an optional consistent SQLite snapshot.
- Added separate backup categories for database/configuration, printers/profiles, materials/inventory, models/files, projects/Workshop designs and print history/photos.
- Added daily, weekly and monthly local backup schedules with time, enabled state, next/last-run visibility and per-schedule retention.
- Added backup history with size, scope, source, Download and Delete controls.
- Added schema, API, archive-content, compatibility and UI-contract regressions for Settings and scheduled backups.

## 0.3.7 — Workshop Shape & Performance Polish

- Removed the redundant D6 palette card while preserving old saved D6 objects as legacy Box geometry.
- Added closed Star, Pyramid, Hex prism, Torus and Tube primitives.
- Added Classic block, Heavy block and Condensed printable lettering options.
- Made left-click-and-hold drag a selected body across the workplane in Move, Resize or Rotate mode, while preserving handle priority and Ctrl camera orbit.
- Captured the pointer during direct movement so dragging remains stable at canvas edges.
- Avoided full mesh/Boolean rebuilds after pure transforms, cached generated primitive geometry and skipped costly feature-edge extraction on meshes above 80,000 triangles.
- Reduced overlay layout work to roughly 30 fps and capped Workshop pixel density at 1.5× for smoother high-DPI interaction.

- Removed native number-stepper controls from Workshop dimension pills and separated axis, value and millimetre lanes so typed measurements remain legible.
- Added closed D4, D6, D8, D10, D12 and D20 blank-die primitives to the Workshop palette.
- Added editable built-in block text with a focused Shape-panel editor, 18-character limit and direct X/Z face sizing plus Y extrusion thickness.
- Generated text as closed printable geometry without browser fonts or network dependencies, preserving solid/hole, grouping, Boolean export and Model Health behaviour.
- Added persistence, sanitisation, UI-contract and exact-package regression coverage for dice and custom text.

- Replaced ordinary left-button camera orbit with direct selection and manipulation; hold Ctrl while dragging to orbit the camera.
- Added drag-box selection from empty workplane space, with Shift preserving the existing selection.
- Added familiar Ctrl+C, Ctrl+V, Ctrl+Z and Ctrl+Y Workshop shortcuts, including group-safe internal copy/paste.
- Added high-contrast square resize handles at corners and edge midpoints plus a top height handle.
- Made edge-handle resizing axis-specific and corner resizing two-axis, always anchoring the opposite side.
- Increased resize-handle hit areas so the visible squares are easy to grab without accidentally moving the model.
- Reworked on-model dimension values into separate X/Y/Z pills with collision avoidance and canvas-edge clamping.
- Reduced Move mode to direct workplane dragging plus a single vertical lift handle, removing unnecessary horizontal arrows.
- Preserved group locking, alignment, Boolean solid/hole previews, STL library previews and print-health-gated export.

## 0.3.4 — Direct Manipulation & Locked Groups

- Added direct workplane dragging for selected shapes, library models and grouped parts in Move mode.
- Added compact Move, Resize and Rotate controls beside the selection and inside the grouped-part inspector.
- Reduced and re-centred transform controls, using world movement and local resize/rotation orientation.
- Normalised every selection so one selected group member always expands to the complete group.
- Fixed grouped Drop-to-bed, which previously lowered hidden members independently and could change the solid/hole relationship.
- Made duplicate and mirror operations preserve independent, locked group membership.
- Added selection-unit alignment so groups can align with other groups or shapes without moving their members apart.
- Removed the move/rotate/resize gizmo while alignment dots are active to reduce visual clutter.
- Restored Model Details previews by reinstating safe mesh styling for STL, OBJ and 3MF files and guarding render callback failures.
- Verified direct group dragging, one-sided typed group resize, group-to-shape alignment and the supplied Bluebell STL preview in the live browser.

## 0.3.3 — CAD Clarity & Alignment

- Removed Workshop shadows and applied crease-aware Boolean normals to prevent dented or melted-looking merged surfaces.
- Added high-contrast feature-edge outlines so solid corners and composed cut edges remain easy to read.
- Added grey diagonal hatching for hole shapes in the workplane, hierarchy and inspector.
- Removed the redundant top-right camera box while retaining the complete left-hand camera controls.
- Added editable width, depth and height dimension lines directly around the selected model.
- Added nine edge-and-centre alignment choices through both on-model dots and a labelled X/Y/Z inspector panel.
- Fixed a competing object-list click handler that could break Shift-selection and reduce a grouped selection to its first member.
- Verified one-sided typed resize, multi-selection, ungroup, alignment, regroup and 100/100 Boolean export in the live browser.
- Added UI contracts for edge rendering, hole hatching, the single-camera layout, measurements, alignment and the selection-handler regression.

## 0.3.2 — Directional Resize & Printable Groups

- Changed resize grips to move only the selected side while anchoring the opposite face.
- Added exact X, Y and Z millimetre fields to the in-canvas Resize selection panel.
- Applied the same one-sided rule to typed dimensions, using the most recently selected grip direction.
- Replaced visual-only grouping with a live Manifold solid/hole preview.
- Made a group select, move, rotate and resize as one printable part.
- Collapsed grouped members into one hierarchy row with a clear grouped-part inspector.
- Kept Ungroup reversible so every source member remains independently editable.
- Added regressions for directional-resize controls, live group composition, grouped document persistence and the packaged export workflow.

## 0.3.1 — Intuitive Workshop

- Expanded the workplane by consolidating the former two side columns into one right-hand shapes/properties dock.
- Added drag-to-workplane primitive placement with grid-snapped drop coordinates while retaining one-click placement.
- Added an empty-design starting guide and visible workplane drop target.
- Added Home, Top, Front and Right camera presets, a clickable view block, zoom buttons and Focus Selection.
- Added a compact selection HUD with immediate Solid, Hole and Focus actions.
- Rebuilt primitive cards with recognisable dimensional previews and clearer placement affordances.
- Added per-object colour selection with practical preset swatches.
- Moved saved-design switching to the header and made the object hierarchy collapsible.
- Added an always-visible shortcut guide for Shift multi-select, Move, Rotate and Resize.
- Preserved exact transforms, grouping, alignment, mirror, undo/redo, library models, robust Manifold Boolean export and automatic Model Health.
- Added new UI-contract and browser interaction coverage for the refined workplane.

## 0.3.0 — Workshop CAD

- Rebuilt Workshop as a full-screen, print-first CAD workbench with editable saved designs.
- Added box, cylinder, sphere, cone and wedge primitives plus non-destructive library-model placement.
- Added direct move/rotate/scale controls, exact millimetre dimensions, grid snapping and keyboard shortcuts.
- Added canvas and scene-list selection, Shift multi-select, duplicate, delete, mirror, align, group, ungroup, drop-to-bed and fit-view actions.
- Added 60-state in-session undo/redo with autosave and optimistic document revisions.
- Added solid/hole composition through the topology-robust Manifold 3D WebAssembly kernel.
- Added non-destructive STL export, source-model lineage and automatic analysis of the exact persisted export.
- Added a compact print-readiness panel showing the latest exported Model Health result.
- Verified a solid box with a cylindrical through-hole exports closed, manifold and at 100/100 Model Health.
- Added Workshop API, persistence, validation, lineage, Boolean-asset, layout and UI-contract regressions.
- Kept Workshop deliberately focused on printable geometry; no electronics or circuit simulation was added.
- Preserved all v0.2.10 Manufacturing Health, Resin Preparation, Safe Repair and resilient bootstrap behaviour.

## 0.2.10 — Exposed Thin-Feature Refinement

- Rejected opposing surfaces that face one another across empty space instead of through material.
- Ranked substantial exposed thin features above smaller connected surface details and ornament.
- Spread Show-on-model markers across each selected feature group.
- Replaced model-specific terminology with generic exposed-feature wording.
- Changed preparation offsets to follow each sampled surface's local outward direction.
- Verified the supplied Bluebell has one dominant exposed thin-feature group, improves from resin score 85 to 90, retains two island candidates and remains watertight at 100 Mesh Health.
- Added air-gap false-positive, exact Bluebell targeting, repair-improvement and generic UI wording regressions.

## 0.2.9 — Resin Preparation

- Added broad thin-feature clustering so substantial geometry is separated from isolated close folds and tiny curls.
- Added a non-destructive 0.50 mm default Resin Preparation child action with a configurable 0.30–2.00 mm target.
- Thickened paired thin-feature surfaces along a detected local direction while preserving mesh connectivity.
- Added conservative orthogonal orientation trials for suction candidates, guarded against island and peel-risk regressions.
- Improved suction and thin-feature Show-on-model markers with area-aware sizing and suction rings.
- Added persisted-child verification gates for topology, resin score, broad thin-region count, suction count and island count.
- Verified the supplied repaired Bluebell remains watertight/100 Mesh Health while its resin score and exposed thin-feature count improve.
- Added exact 0.20 mm exposed-feature, suction-orientation, UI/API and optional supplied-Bluebell regressions.

## 0.2.8 — Bluebell Repair Correction

- Analysed and repaired the supplied 484,594-face Bluebell STL end to end.
- Distinguished ordinary surface duplicates from edge-isolated two-sided coincident sheets.
- Removed all 10 faces across Bluebell's five zero-thickness duplicate pairs rather than keeping five open triangles.
- Added report metrics and clearer wording for isolated duplicate-sheet groups/faces.
- Added a permanent synthetic regression matching Bluebell's five-component connectivity pattern.
- Verified the real API workflow improves Bluebell from 95/100 to 100/100 while remaining watertight.

## 0.2.7 — Topology Repair Correction

- Fixed false duplicate detection caused by independently sorting triangle coordinate axes.
- Canonicalized duplicate faces using complete rounded vertex-coordinate IDs.
- Replaced directed boundary chaining with winding-independent undirected boundary-loop traversal.
- Added a regression matching five shells, five missing faces and 15 boundary edges; repair restores watertightness and improves the score.
- Added a coordinate-collision regression proving distinct triangles are not duplicates.
- Added fail-closed repair validation: score cannot decrease and boundary/non-manifold/duplicate counts cannot increase.
- Advanced the Mesh Health engine cache version to invalidate incorrect earlier reports.

## 0.2.6 — Verified Deployment Hotfix

- Restored the original suite ZIP root at that release stage to prevent parallel extraction from rebuilding an older project folder.
- Added the running version to the Model Details label.
- Forced a fresh persisted-file health analysis immediately after opening a created or reused Safe Repair child.
- Added release-contract coverage for the version marker and forced refresh path.
- Retained the v0.2.5 five-duplicate repair verification and full-height nested sticky layout.

## 0.2.5 — Repair Verification & Sticky Preview

- Verified Safe Repair against the persisted STL and failed closed if duplicate faces remain.
- Added an exact five-duplicate regression with mixed winding.
- Fixed repeated repair attempts to reuse and open the existing verified clean child.
- Added explicit created/reused repair feedback with remaining duplicate count.
- Reworked the sticky layout using a full-height grid column plus nested sticky wrapper.
- Moved thumbnail-angle controls into a non-overlapping card below the 3D preview.
- Verified the real rendered modal at initial, intermediate, and maximum scroll positions.

## 0.2.4 — Pass 10.1 Health Refinement Hotfix

- Fixed Safe Repair duplicate removal by comparing triangle coordinates independently of vertex indexes and winding.
- Verified the saved repaired child reports zero duplicate faces during a forced fresh analysis.
- Moved sticky positioning from the 3D canvas to the complete Model Details preview column so it follows the full health report.
- Preserved **Show on model** marker behavior in the sticky preview.
- Added desktop and responsive sticky-layout contract coverage.
- Advanced the mesh-health engine cache version so affected reports are recalculated.
- Retained all v0.2.3 Manufacturing Health checks and resilient frontend/bootstrap behavior.

## 0.2.3 — Pass 10.1 Manufacturing Health

- Separated Mesh Health from printer-aware Manufacturing Health.
- Added sampled thin-wall/delicate-feature screening with printer-aware thresholds.
- Added representative 3D risk markers and **Show on model** support.
- Added resin sealed/nested cavity and trapped-resin screening.
- Added low-confidence downward suction-pocket candidate detection.
- Added resin unsupported local-minimum/island-risk screening.
- Added projected-area / peel-load proxy by Z.
- Added FDM overhang, severe-overhang, bridge-like-region and bed-contact screening.
- Added manufacturing report cache per model + printer with printer-setting signature invalidation.
- Improved inverted-shell explanation.
- Added `manufacturing_reports` cache table; schema version 121.
- Retained v0.2.2 resilient inline frontend bootstrap and all previous Pass 10 repair functionality.

## 0.2.2 — Resilient Frontend Bootstrap

- Core LayerVault CSS and JavaScript embedded in the root HTML response.
- Safe browser storage wrapper and lazy Three.js bootstrap.
- Visible frontend boot diagnostics instead of silent blank pages.
