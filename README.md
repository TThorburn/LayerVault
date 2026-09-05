# LayerVault v0.3.28 — Self-hosted 3D Printing Suite

LayerVault is a local-first Docker workspace for 3D model libraries, projects, printer and material inventory, print recipes, results, and browser-native model preparation.

## What changed in v0.3.28

- Standardised the application, release archive and extracted directory name as **LayerVault** / `layervault-suite`.
- Licensed LayerVault under GNU AGPL-3.0-only, with the complete licence and third-party notices included in the release.
- Clarified the intended trusted home/workshop LAN deployment and the separate ports used by LayerVault and Workshop.
- Retained complete artwork coverage for the supported printer catalogue, with custom user photos always taking priority.

LayerVault uses open databases for importable records and official manufacturer pages for product artwork. Filament Cheat Sheet and FilamentDB are useful research references, but their datasets are not bundled because no redistribution licence or supported public API was identified.

## Install or upgrade

From the folder containing `docker-compose.yml`:

```powershell
docker compose down --remove-orphans
docker compose up -d --build
```

The first command removes obsolete slicer containers left by an older Compose file. It does not delete the bind-mounted LayerVault data folders.

Open LayerVault at `http://localhost:8088`. SketchForge runs at `http://localhost:3004` and opens inside Workshop.

## Network and self-hosting

LayerVault is designed for a trusted home, studio or workshop network. Docker publishes two ports on the host:

- `8088` — the LayerVault application.
- `3004` — the browser-native SketchForge Workshop loaded inside LayerVault.

Both ports must be reachable by devices using LayerVault on the local network. Do **not** forward either port directly from your router or expose them unprotected to the public internet. For access away from home, use a trusted VPN or a properly configured reverse proxy with authentication and HTTPS.

Optional `APP_USERNAME` and `APP_PASSWORD` values in `.env` protect the LayerVault application on port 8088. They do not protect the separate Workshop service on port 3004, so the supplied configuration should still be treated as LAN-only.

## Storage locations

Copy `.env.example` to `.env` to place the working area, database, model originals, and backups on separate host folders, disks, or mounted NAS shares:

```dotenv
LAYERVAULT_DATA_PATH=./data
LAYERVAULT_DATABASE_PATH=./data
LAYERVAULT_MODELS_PATH=//PRINT-NAS/3d-models
LAYERVAULT_BACKUPS_PATH=//BACKUP-NAS/layervault
```

Windows paths may use forward slashes, for example `D:/LayerVault/database` or `//server/share/models`. Docker Desktop must be allowed to access the chosen location. On Linux, mount a NAS share on the host first and use its absolute mount path.

## Printer artwork and attribution

- Resin artwork is retained from the MIT-licensed Anycubic, Elegoo, and Athena DragonFruit printer plugin packs.
- FDM artwork is retained from OrcaSlicer's AGPL-3.0 printer profile library.
- LayerVault retains a data-only subset of UVtools resin profiles and can query upstream OrcaSlicer profile data when needed; neither application runtime is bundled or launched.

See `THIRD_PARTY_NOTICES.md` and `third_party/printer-artwork/orcaslicer/LICENSE.txt` for attribution and licence details.

## Licence

LayerVault is licensed under the **GNU Affero General Public License v3.0 only** (`AGPL-3.0-only`). See `LICENSE` for the complete terms. Separately copyrighted bundled components retain their own notices and licences in `THIRD_PARTY_NOTICES.md` and their respective `third_party` directories.

## Workshop

SketchForge supplies the complete browser-native CAD editor without a streamed desktop or VNC. Save important projects as **Shared** so they persist under `data/sketchforge/projects` and are included in LayerVault backups.

SketchForge is created by Formsmith746 and contributors and licensed AGPL-3.0-only. Its corresponding source is included under `third_party/sketchforge`.
