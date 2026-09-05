import photonPrinters from './printers/photon-series.json';
import photonMonoPrinters from './printers/photon-mono-series.json';
import photonMonoXPrinters from './printers/photon-mono-x-series.json';
import photonMonoMPrinters from './printers/photon-mono-m-series.json';
import photonMPrinters from './printers/photon-m-series.json';
import photonPPrinters from './printers/photon-p-series.json';
import type { PrinterPreset } from '../../src/features/profiles/profileStore';

function resolvePresetImagePath(imageAssetPath: unknown): string | undefined {
  if (typeof imageAssetPath !== 'string' || !imageAssetPath.trim()) return undefined;
  const trimmed = imageAssetPath.trim();
  if (trimmed.startsWith('/') || trimmed.startsWith('http')) return trimmed;
  const normalized = trimmed.startsWith('./') ? trimmed.slice(2) : trimmed;
  return `/plugins/anycubic/printers/${normalized}`;
}

function mapPresets(presets: any[]) {
  return presets.map((preset) => ({
    ...preset,
    imageAssetPath: resolvePresetImagePath(preset.imageAssetPath),
  }));
}

export const ANYCUBIC_PLUGIN_MANIFEST = {
  schemaVersion: 1,
  id: 'anycubic-builtin',
  name: 'Anycubic Plugin',
  version: '0.1.0',
  description: 'Anycubic printer profile pack (AFF and AZF format support).',
  printerPresets: [
    ...mapPresets(photonPPrinters as any[]),
    ...mapPresets(photonMonoMPrinters as any[]),
    ...mapPresets(photonMonoPrinters as any[]),
    ...mapPresets(photonMonoXPrinters as any[]),
    ...mapPresets(photonMPrinters as any[]),
    ...mapPresets(photonPrinters as any[])
  ] as PrinterPreset[],
  materialTemplates: [],
};
