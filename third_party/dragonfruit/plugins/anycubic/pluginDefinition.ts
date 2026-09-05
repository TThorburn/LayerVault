import type {
  ComplexPluginDefinition,
  PluginLocalMaterialSettingsAdapterContract,
} from '@/features/plugins/complexPluginContracts';
import { ANYCUBIC_PLUGIN_MANIFEST } from './pluginManifest';
import { ANYCUBIC_AFF_FORMAT_DEFINITION } from './slicing/affFormatDefinition';
import { ANYCUBIC_AZF_FORMAT_DEFINITION } from './slicing/azfFormatDefinition';

// ─── Local material settings adapters (per mode) ─────────────────────

type AnycubicModeSettingsSchema = Omit<PluginLocalMaterialSettingsAdapterContract, 'outputFormat'>;

const ANYCUBIC_SIMPLE_SETTINGS_BASE: AnycubicModeSettingsSchema = {
  displayName: 'Anycubic Resin Settings',
  replacesDefaultMaterialSettings: true,
  tabs: [
    { id: 'simple', title: 'Simple', order: 10 },
  ],
  sections: [
    { id: 'layers-exposure', title: 'Layers and Exposure', tabId: 'simple', order: 10 },
    { id: 'print-control', title: 'Print Control', tabId: 'simple', order: 20 },
  ],
  cards: [
    { id: 'layers-exposure-card', title: 'Layers and Exposure', tabId: 'simple', sectionId: 'layers-exposure', order: 10 },
    { id: 'print-control-card', title: 'Print Control', tabId: 'simple', sectionId: 'print-control', order: 10 },
  ],
  fields: [
    // ── Layers and Exposure ──────────────────────────────────────────
    {
      key: 'layerHeightMm',
      label: 'Layer Thickness (mm)',
      kind: 'number' as const,
      defaultValue: 0.05,
      min: 0.001,
      max: 1,
      step: 0.001,
      placement: { tabId: 'simple', sectionId: 'layers-exposure', cardId: 'layers-exposure-card', order: 10 },
      metadataPath: 'material.layerHeightMm',
    },
    {
      key: 'normalExposureSec',
      label: 'Normal Exposure Time (s)',
      kind: 'number' as const,
      defaultValue: 2.0,
      min: 0,
      max: 300,
      step: 0.001,
      placement: { tabId: 'simple', sectionId: 'layers-exposure', cardId: 'layers-exposure-card', order: 20 },
      metadataPath: 'material.normalExposureSec',
    },
    {
      key: 'bottomLayerCount',
      label: 'Bottom Layers',
      kind: 'integer' as const,
      defaultValue: 5,
      min: 0,
      max: 200,
      step: 1,
      placement: { tabId: 'simple', sectionId: 'layers-exposure', cardId: 'layers-exposure-card', order: 30 },
      metadataPath: 'material.bottomLayerCount',
    },
    {
      key: 'bottomExposureSec',
      label: 'Bottom Exposure Time (s)',
      kind: 'number' as const,
      defaultValue: 45.0,
      min: 0,
      max: 300,
      step: 0.001,
      placement: { tabId: 'simple', sectionId: 'layers-exposure', cardId: 'layers-exposure-card', order: 40 },
      metadataPath: 'material.bottomExposureSec',
    },
    {
      key: 'transitionLayerCount',
      label: 'Transition Layer Count',
      kind: 'integer' as const,
      defaultValue: 15,
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'simple', sectionId: 'layers-exposure', cardId: 'layers-exposure-card', order: 50 },
      metadataPath: 'material.transitionLayerCount',
    },
    {
      key: 'waitTimeBeforeCureSec',
      label: 'Off Time (s)',
      kind: 'number' as const,
      defaultValue: 1.0,
      min: 0,
      max: 120,
      step: 0.001,
      placement: { tabId: 'simple', sectionId: 'layers-exposure', cardId: 'layers-exposure-card', order: 60 },
      metadataPath: 'material.waitTimeBeforeCureSec',
    },

    // ── Print Control ────────────────────────────────────────────────
    {
      key: 'liftDistanceMm',
      label: 'Z Lift Distance (mm)',
      kind: 'number' as const,
      defaultValue: 5.0,
      min: 0,
      max: 50,
      step: 0.001,
      placement: { tabId: 'simple', sectionId: 'print-control', cardId: 'print-control-card', order: 10 },
      metadataPath: 'material.liftDistanceMm',
    },
    {
      key: 'liftSpeedMmMin',
      label: 'Z Lift Speed (mm/min)',
      kind: 'number' as const,
      defaultValue: 120,
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'simple', sectionId: 'print-control', cardId: 'print-control-card', order: 20 },
      metadataPath: 'material.liftSpeedMmMin',
    },
    {
      key: 'retractSpeedMmMin',
      label: 'Z Retract Speed (mm/min)',
      kind: 'number' as const,
      defaultValue: 120,
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'simple', sectionId: 'print-control', cardId: 'print-control-card', order: 30 },
      metadataPath: 'material.retractSpeedMmMin',
    },
    {
      key: 'intelligentRelease',
      label: 'Intelligent Release',
      kind: 'boolean' as const,
      defaultValue: false,
      placement: { tabId: 'simple', sectionId: 'print-control', cardId: 'print-control-card', order: 40 },
      metadataPath: 'material.intelligentRelease',
    },
    {
      key: 'targetTemperatureC',
      label: 'Target Temperature (°C)',
      kind: 'number' as const,
      defaultValue: 25,
      min: 0,
      max: 100,
      step: 1,
      placement: { tabId: 'simple', sectionId: 'print-control', cardId: 'print-control-card', order: 50 },
      metadataPath: 'material.targetTemperatureC',
    },
  ],
};

const ANYCUBIC_TWOSTAGE_SETTINGS_BASE: AnycubicModeSettingsSchema = {
  displayName: 'Anycubic Resin Settings',
  replacesDefaultMaterialSettings: true,
  tabs: [
    { id: 'twostage', title: 'Advanced', order: 10 },
  ],
  sections: [
    { id: 'layers-exposure-ts', title: 'Layers and Exposure', tabId: 'twostage', order: 10 },
    { id: 'normal-layers', title: 'Normal Layers Control', tabId: 'twostage', order: 20 },
    { id: 'bottom-layers', title: 'Bottom Layers Control', tabId: 'twostage', order: 30 },
  ],
  cards: [
    { id: 'layers-exposure-ts-card', title: 'Layers and Exposure', tabId: 'twostage', sectionId: 'layers-exposure-ts', order: 10 },
    { id: 'normal-layers-card', title: 'Normal Layers Control', tabId: 'twostage', sectionId: 'normal-layers', order: 10 },
    { id: 'bottom-layers-card', title: 'Bottom Layers Control', tabId: 'twostage', sectionId: 'bottom-layers', order: 10 },
  ],
  fields: [
    // ── Layers and Exposure ──────────────────────────────────────────
    {
      key: 'layerHeightMm',
      label: 'Layer Thickness (mm)',
      kind: 'number' as const,
      defaultValue: 0.05,
      min: 0.001,
      max: 1,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'layers-exposure-ts', cardId: 'layers-exposure-ts-card', order: 10 },
      metadataPath: 'material.layerHeightMm',
    },
    {
      key: 'normalExposureSec',
      label: 'Normal Exposure Time (s)',
      kind: 'number' as const,
      defaultValue: 2.0,
      min: 0,
      max: 300,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'layers-exposure-ts', cardId: 'layers-exposure-ts-card', order: 20 },
      metadataPath: 'material.normalExposureSec',
    },
    {
      key: 'waitTimeBeforeCureSec',
      label: 'Off Time (s)',
      kind: 'number' as const,
      defaultValue: 1.0,
      min: 0,
      max: 120,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'layers-exposure-ts', cardId: 'layers-exposure-ts-card', order: 30 },
      metadataPath: 'material.waitTimeBeforeCureSec',
    },
    {
      key: 'bottomExposureSec',
      label: 'Bottom Exposure Time (s)',
      kind: 'number' as const,
      defaultValue: 45.0,
      min: 0,
      max: 300,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'layers-exposure-ts', cardId: 'layers-exposure-ts-card', order: 40 },
      metadataPath: 'material.bottomExposureSec',
    },
    {
      key: 'bottomLayerCount',
      label: 'Bottom Layers',
      kind: 'integer' as const,
      defaultValue: 5,
      min: 0,
      max: 200,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'layers-exposure-ts', cardId: 'layers-exposure-ts-card', order: 50 },
      metadataPath: 'material.bottomLayerCount',
    },
    {
      key: 'transitionLayerCount',
      label: 'Transition Layer Count',
      kind: 'integer' as const,
      defaultValue: 15,
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'layers-exposure-ts', cardId: 'layers-exposure-ts-card', order: 60 },
      metadataPath: 'material.transitionLayerCount',
    },

    // ── Normal Layers Control ────────────────────────────────────────
    {
      key: 'liftDistanceMm',
      label: 'Z Lift Distance (mm)',
      kind: 'number' as const,
      defaultValue: 3.0,
      splitWithKey: 'liftDistance2Mm',
      tag: 'Slow',
      min: 0,
      max: 50,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'normal-layers', cardId: 'normal-layers-card', order: 10 },
      metadataPath: 'material.liftDistanceMm',
    },
    {
      key: 'liftDistance2Mm',
      label: 'Z Lift Distance Step 2 (mm)',
      kind: 'number' as const,
      defaultValue: 5.0,
      tag: 'Fast',
      min: 0,
      max: 50,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'normal-layers', cardId: 'normal-layers-card', order: 11 },
      metadataPath: 'material.liftDistance2Mm',
    },
    {
      key: 'liftSpeedMmMin',
      label: 'Z Lift Speed (mm/min)',
      kind: 'number' as const,
      defaultValue: 120,
      splitWithKey: 'liftSpeed2MmMin',
      tag: 'Slow',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'normal-layers', cardId: 'normal-layers-card', order: 20 },
      metadataPath: 'material.liftSpeedMmMin',
    },
    {
      key: 'liftSpeed2MmMin',
      label: 'Z Lift Speed Step 2 (mm/min)',
      kind: 'number' as const,
      defaultValue: 360,
      tag: 'Fast',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'normal-layers', cardId: 'normal-layers-card', order: 21 },
      metadataPath: 'material.liftSpeed2MmMin',
    },
    {
      key: 'retractSpeed2MmMin',
      label: 'Z Retract Speed (mm/min)',
      kind: 'number' as const,
      defaultValue: 360,
      splitWithKey: 'retractSpeedMmMin',
      tag: 'Fast',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'normal-layers', cardId: 'normal-layers-card', order: 30 },
      metadataPath: 'material.retractSpeed2MmMin',
    },
    {
      key: 'retractSpeedMmMin',
      label: 'Z Retract Speed Step 2 (mm/min)',
      kind: 'number' as const,
      defaultValue: 120,
      tag: 'Slow',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'normal-layers', cardId: 'normal-layers-card', order: 31 },
      metadataPath: 'material.retractSpeedMmMin',
    },

    // ── Bottom Layers Control ────────────────────────────────────────
    {
      key: 'bottomLiftDistanceMm',
      label: 'Z Lift Distance (mm)',
      kind: 'number' as const,
      defaultValue: 5.0,
      splitWithKey: 'bottomLiftDistance2Mm',
      tag: 'Slow',
      min: 0,
      max: 50,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'bottom-layers', cardId: 'bottom-layers-card', order: 10 },
      metadataPath: 'material.bottomLiftDistanceMm',
    },
    {
      key: 'bottomLiftDistance2Mm',
      label: 'Z Lift Distance Step 2 (mm)',
      kind: 'number' as const,
      defaultValue: 3.0,
      tag: 'Fast',
      min: 0,
      max: 50,
      step: 0.001,
      placement: { tabId: 'twostage', sectionId: 'bottom-layers', cardId: 'bottom-layers-card', order: 11 },
      metadataPath: 'material.bottomLiftDistance2Mm',
    },
    {
      key: 'bottomLiftSpeedMmMin',
      label: 'Z Lift Speed (mm/min)',
      kind: 'number' as const,
      defaultValue: 120,
      splitWithKey: 'bottomLiftSpeed2MmMin',
      tag: 'Slow',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'bottom-layers', cardId: 'bottom-layers-card', order: 20 },
      metadataPath: 'material.bottomLiftSpeedMmMin',
    },
    {
      key: 'bottomLiftSpeed2MmMin',
      label: 'Z Lift Speed Step 2 (mm/min)',
      kind: 'number' as const,
      defaultValue: 180,
      tag: 'Fast',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'bottom-layers', cardId: 'bottom-layers-card', order: 21 },
      metadataPath: 'material.bottomLiftSpeed2MmMin',
    },
    {
      key: 'bottomRetractSpeed2MmMin',
      label: 'Z Retract Speed (mm/min)',
      kind: 'number' as const,
      defaultValue: 240,
      splitWithKey: 'bottomRetractSpeedMmMin',
      tag: 'Fast',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'bottom-layers', cardId: 'bottom-layers-card', order: 30 },
      metadataPath: 'material.bottomRetractSpeed2MmMin',
    },
    {
      key: 'bottomRetractSpeedMmMin',
      label: 'Z Retract Speed Step 2 (mm/min)',
      kind: 'number' as const,
      defaultValue: 180,
      tag: 'Slow',
      min: 0,
      max: 100000,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'bottom-layers', cardId: 'bottom-layers-card', order: 31 },
      metadataPath: 'material.bottomRetractSpeedMmMin',
    },

    // ── Additional Print Control ─────────────────────────────────────
    {
      key: 'targetTemperatureC',
      label: 'Target Temperature (°C)',
      kind: 'number' as const,
      defaultValue: 25,
      min: 0,
      max: 100,
      step: 1,
      placement: { tabId: 'twostage', sectionId: 'layers-exposure-ts', cardId: 'layers-exposure-ts-card', order: 70 },
      metadataPath: 'material.targetTemperatureC',
    },
  ],
};

// ─── Per-format adapters (keyed by mode) ─────────────────────────────

function withoutField(
  base: AnycubicModeSettingsSchema,
  fieldKey: string,
) {
  return { ...base, fields: base.fields.filter((f) => f.key !== fieldKey) };
}

const ANYCUBIC_AZF_SIMPLE: PluginLocalMaterialSettingsAdapterContract = {
  outputFormat: ANYCUBIC_AZF_FORMAT_DEFINITION.outputFormat,
  ...ANYCUBIC_SIMPLE_SETTINGS_BASE,
};

const ANYCUBIC_AZF_SIMPLE_NO_TEMP: PluginLocalMaterialSettingsAdapterContract = {
  outputFormat: ANYCUBIC_AZF_FORMAT_DEFINITION.outputFormat,
  ...withoutField(ANYCUBIC_SIMPLE_SETTINGS_BASE, 'targetTemperatureC'),
};

const ANYCUBIC_AZF_TWOSTAGE: PluginLocalMaterialSettingsAdapterContract = {
  outputFormat: ANYCUBIC_AZF_FORMAT_DEFINITION.outputFormat,
  ...ANYCUBIC_TWOSTAGE_SETTINGS_BASE,
};

const ANYCUBIC_AZF_TWOSTAGE_NO_TEMP: PluginLocalMaterialSettingsAdapterContract = {
  outputFormat: ANYCUBIC_AZF_FORMAT_DEFINITION.outputFormat,
  ...withoutField(ANYCUBIC_TWOSTAGE_SETTINGS_BASE, 'targetTemperatureC'),
};

const ANYCUBIC_AFF_SIMPLE: PluginLocalMaterialSettingsAdapterContract = {
  outputFormat: ANYCUBIC_AFF_FORMAT_DEFINITION.outputFormat,
  ...ANYCUBIC_SIMPLE_SETTINGS_BASE,
};

const ANYCUBIC_AFF_TWOSTAGE: PluginLocalMaterialSettingsAdapterContract = {
  outputFormat: ANYCUBIC_AFF_FORMAT_DEFINITION.outputFormat,
  ...ANYCUBIC_TWOSTAGE_SETTINGS_BASE,
};

// ─── Extension → mode map helpers ────────────────────────────────────

function azfModeMap() {
  return { simple: ANYCUBIC_AZF_SIMPLE, twostage: ANYCUBIC_AZF_TWOSTAGE };
}

function azfModeMapNoTemp() {
  return { simple: ANYCUBIC_AZF_SIMPLE_NO_TEMP, twostage: ANYCUBIC_AZF_TWOSTAGE_NO_TEMP };
}

function affModeMap() {
  return { simple: ANYCUBIC_AFF_SIMPLE, twostage: ANYCUBIC_AFF_TWOSTAGE };
}

// ─── Plugin definition ──────────────────────────────────────────────

export const ANYCUBIC_COMPLEX_PLUGIN_DEFINITION: ComplexPluginDefinition = {
  id: 'anycubic',
  manifest: ANYCUBIC_PLUGIN_MANIFEST,
  capabilities: {
    networkOperations: false,
    uploadWithProgress: false,
    slicerEncoder: true,
    tauriRuntimePlugin: false,
  },
  slicingFormatsByOutput: {
    '.aff': ANYCUBIC_AFF_FORMAT_DEFINITION,
    '.azf': ANYCUBIC_AZF_FORMAT_DEFINITION,
  },
  localMaterialSettingsByOutput: {
    // Canonical format keys
    '.aff': ANYCUBIC_AFF_SIMPLE,
    '.azf': ANYCUBIC_AZF_SIMPLE,
  },
  localMaterialSettingsByOutputAndMode: {
    // Canonical format keys
    '.aff': affModeMap(),
    '.azf': azfModeMap(),
  },
};

export default ANYCUBIC_COMPLEX_PLUGIN_DEFINITION;
