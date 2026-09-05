<p align="center">
  <img src="docs/images/layervault-readme-hero.png" alt="LayerVault — your self-hosted 3D printing workspace" width="100%">
</p>

# LayerVault

<p align="center">
  <strong>Keep every model, material, machine and successful print recipe in one local workspace.</strong>
</p>

<p align="center">
  <img alt="Version 0.3.29" src="https://img.shields.io/badge/version-0.3.29-476dff?style=for-the-badge">
  <img alt="AGPL-3.0-only" src="https://img.shields.io/badge/licence-AGPL--3.0-6547e8?style=for-the-badge">
  <img alt="Docker Compose" src="https://img.shields.io/badge/Docker-Compose-2496ed?style=for-the-badge&logo=docker&logoColor=white">
  <img alt="Self-hosted" src="https://img.shields.io/badge/self--hosted-LAN--first-17a673?style=for-the-badge">
</p>

LayerVault is a local-first 3D-printing suite for cataloguing model files, planning projects, tracking printers and stock, recording print results and preparing models in a browser-native workshop. Your database, originals and backups stay on storage you control.

> [!IMPORTANT]
> LayerVault is intended for a trusted home, studio or workshop network. Do not expose ports `8088` or `3004` directly to the public internet.

## A look inside

<p align="center">
  <img src="docs/images/layervault-dashboard.png" alt="LayerVault dashboard in the Frost glass theme" width="100%">
</p>

<p align="center"><sub>The LayerVault dashboard in the Frost glass theme.</sub></p>

## Everything around the print

| | Workspace | What it handles |
|---:|---|---|
| 📦 | **Model Library** | Searchable originals, thumbnails, tags, creator details, licences and model health checks. |
| 🗂️ | **Projects** | Group models into builds, set quantities and variants, and prioritise what should print first. |
| 🧰 | **Workshop** | Browser-native SketchForge preparation and CAD tools—no streamed desktop or VNC session. |
| 🧵 | **Materials & Stock** | Filament spools and resin bottles with colour, remaining stock, cost, photos and catalogue data. |
| 🖨️ | **Printers & Profiles** | Physical machines, FDM/resin profiles, defaults and matching printer artwork. |
| 🧾 | **Print Lab** | Queue jobs, attach multiple models, inspect sliced files and preserve the settings behind each result. |
| 💾 | **Settings & Backups** | Glass themes, separate storage locations and scheduled scoped backups. |

## Quick start

### Requirements

- Docker Desktop, or Docker Engine with the Compose plugin
- Enough local disk space for the application build
- A mounted disk or NAS share if model files or backups live elsewhere

### Start LayerVault

From the directory containing `docker-compose.yml`:

```bash
docker compose up -d --build
```

Then open:

- **LayerVault:** [http://localhost:8088](http://localhost:8088)
- **Workshop:** [http://localhost:3004](http://localhost:3004), loaded inside LayerVault
- **Health check:** [http://localhost:8088/health](http://localhost:8088/health)

Check that both services are healthy:

```bash
docker compose ps
```

### Updating an existing installation

```bash
docker compose down --remove-orphans
docker compose up -d --build
```

The first command removes containers retired from older LayerVault releases. It does **not** delete your bind-mounted data folders.

## Storage that fits your setup

Copy `.env.example` to `.env`, then keep everything together or split the database, model originals and backups across separate disks or mounted NAS shares.

```dotenv
LAYERVAULT_DATA_PATH=./data
LAYERVAULT_DATABASE_PATH=./data
LAYERVAULT_MODELS_PATH=//PRINT-NAS/3d-models
LAYERVAULT_BACKUPS_PATH=//BACKUP-NAS/layervault
```

| Setting | Purpose | Default |
|---|---|---|
| `LAYERVAULT_DATA_PATH` | Working data, thumbnails, uploads, print photos and Workshop projects | `./data` |
| `LAYERVAULT_DATABASE_PATH` | SQLite database directory | `./data` |
| `LAYERVAULT_MODELS_PATH` | Original model files | `./data/files` |
| `LAYERVAULT_BACKUPS_PATH` | Manual and scheduled backup archives | `./data/backups` |
| `LAYERVAULT_TIMEZONE` | Timestamps and backup schedules | `Europe/London` |
| `APP_USERNAME` / `APP_PASSWORD` | Optional HTTP Basic authentication for LayerVault | Disabled when the password is blank |

Windows paths can use forward slashes, for example `D:/LayerVault/database` or `//server/share/models`. Docker Desktop must be allowed to access the selected location. On Linux, mount a NAS share on the host first and use its absolute mount path.

## How it fits together

```mermaid
flowchart LR
    B[Browser on trusted LAN]
    L[LayerVault<br/>port 8088]
    W[SketchForge Workshop<br/>port 3004]
    DB[(SQLite database)]
    M[(Model originals)]
    BK[(Backup location)]
    P[(Shared Workshop projects)]

    B --> L
    L --> W
    L --> DB
    L --> M
    L --> BK
    W --> P
```

The main application and Workshop are separate services because the browser loads SketchForge directly. Optional `APP_USERNAME` and `APP_PASSWORD` values protect LayerVault on port `8088`; they do not protect Workshop on port `3004`. Keep both services on a trusted LAN, or place them behind a properly secured VPN or reverse proxy.

## Print-file inspection

Print Lab can attach common sliced-print formats and retain any recognised estimates and parameters with the print record. This keeps the settings used for a successful print even after a starting profile changes. Detection is best-effort because slicers and printer vendors store metadata differently; every imported value remains editable before the record is saved.

## Printer and material catalogues

LayerVault combines retained, licence-compatible printer profile data and artwork with user-editable local records. Custom photos always take priority over catalogue artwork. Material imports preserve colour and useful product specifications, while generated colour-accurate spool or bottle artwork fills gaps until an exact photo is supplied.

Useful research sources such as Filament Cheat Sheet and FilamentDB are not bundled because no suitable redistribution licence or supported public API was identified.

## Workshop persistence

SketchForge supplies the complete browser-native CAD editor. Save important Workshop projects as **Shared** so they persist under `data/sketchforge/projects` and are included in LayerVault backups.

## Open-source credits

LayerVault is built alongside excellent open-source work:

- [SketchForge-3D](https://github.com/Formsmith746/SketchForge-3D) by Formsmith746 and contributors powers the browser-native Workshop.
- [DragonFruit](https://github.com/Open-Resin-Alliance/DragonFruit) contributes retained MIT-licensed Anycubic, Elegoo and Athena resin-printer artwork.
- [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) contributes AGPL-3.0 FDM profile data and printer artwork.
- [UVtools](https://github.com/sn4k3/UVtools) contributes a retained data-only subset of resin-printer profiles.

LayerVault does not bundle or launch the DragonFruit, OrcaSlicer or UVtools application runtimes. Full notices and component licences are in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and the corresponding `third_party` directories.

## Release notes

See [`CHANGELOG.md`](CHANGELOG.md) for the complete version history. LayerVault v0.3.29 introduced the new layered-vault identity, browser icons and polished project artwork used throughout this README.

## Licence

LayerVault is licensed under the **GNU Affero General Public License v3.0 only** (`AGPL-3.0-only`). See [`LICENSE`](LICENSE) for the complete terms. Separately copyrighted bundled components retain their own notices and licences.

---

<p align="center">
  <img src="app/static/branding/layervault-logo-192.png" alt="LayerVault logo" width="72">
  <br>
  <strong>Built for the printers, files and recipes on your own network.</strong>
</p>
