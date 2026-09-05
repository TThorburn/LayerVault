//! Per-printer machine profiles for AFF (Anycubic File Format).
//!
//! Each of the 21 supported AFF extensions maps to a `AffMachineProfile`
//! const carrying the printer's identity (machine name, display size, etc.),
//! the highest format version supported, and which RLE codec is used.
//! Values are sourced from UVTools `AnycubicFile.cs` switch statements.

use super::aff_codec::AffRleFormat;
use crate::types::SliceJobV3;
use serde_json::Value;

#[derive(Debug, Clone)]
pub(super) struct AffMachineProfile {
    #[allow(dead_code)]
    pub key_suffix: &'static str,
    pub machine_name: &'static str,
    pub max_version: u16,
    #[allow(dead_code)]
    pub rle_format: AffRleFormat,
    pub display_width_mm: f32,
    pub display_height_mm: f32,
    pub machine_z_mm: f32,
    pub default_pixel_um: f32,
    pub layer_image_format: &'static str,
    pub preview_size: [u32; 2],
    pub preview2_size: [u32; 2],
}

// ── Per-extension profiles ──────────────────────────────────────────
// Values from UVTools AnycubicFile.cs DisplayWidth/DisplayHeight/MachineZ/MachineName
// switches and GetAvailableVersionsForExtension version table.

const PROFILE_PWS: AffMachineProfile = AffMachineProfile {
    key_suffix: "pws", machine_name: "Photon S", max_version: 1,
    rle_format: AffRleFormat::Pws,
    display_width_mm: 120.96, display_height_mm: 68.04, machine_z_mm: 165.0,
    default_pixel_um: 47.25, layer_image_format: "pwsImg",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PW0: AffMachineProfile = AffMachineProfile {
    key_suffix: "pw0", machine_name: "Photon Zero", max_version: 1,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 98.637, display_height_mm: 55.44, machine_z_mm: 150.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PWX: AffMachineProfile = AffMachineProfile {
    key_suffix: "pwx", machine_name: "Photon X", max_version: 1,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 192.0, display_height_mm: 120.0, machine_z_mm: 245.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_DLP: AffMachineProfile = AffMachineProfile {
    key_suffix: "dlp", machine_name: "Photon Ultra", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 102.40, display_height_mm: 57.60, machine_z_mm: 165.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_DL2P: AffMachineProfile = AffMachineProfile {
    key_suffix: "dl2p", machine_name: "Photon D2", max_version: 517,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 130.56, display_height_mm: 73.44, machine_z_mm: 165.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PWMO: AffMachineProfile = AffMachineProfile {
    key_suffix: "pwmo", machine_name: "Photon Mono", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 130.56, display_height_mm: 82.62, machine_z_mm: 165.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PM3N: AffMachineProfile = AffMachineProfile {
    key_suffix: "pm3n", machine_name: "Photon Mono 2", max_version: 517,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 143.36, display_height_mm: 89.60, machine_z_mm: 165.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

// NOTE: pm4n max_version=518 inferred from UVTools default fallthrough.
// Downgrade to 517 if firmware reports indicate v518 isn't accepted.
const PROFILE_PM4N: AffMachineProfile = AffMachineProfile {
    key_suffix: "pm4n", machine_name: "Photon Mono 4", max_version: 518,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 153.408, display_height_mm: 87.040, machine_z_mm: 165.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PWMS: AffMachineProfile = AffMachineProfile {
    key_suffix: "pwms", machine_name: "Photon Mono SE", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 130.56, display_height_mm: 82.62, machine_z_mm: 160.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PWMA: AffMachineProfile = AffMachineProfile {
    key_suffix: "pwma", machine_name: "Photon Mono 4K", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 134.40, display_height_mm: 84.0, machine_z_mm: 165.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PWMX: AffMachineProfile = AffMachineProfile {
    key_suffix: "pwmx", machine_name: "Photon Mono X", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 192.0, display_height_mm: 120.0, machine_z_mm: 245.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PMX2: AffMachineProfile = AffMachineProfile {
    key_suffix: "pmx2", machine_name: "Photon Mono X2", max_version: 517,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 196.61, display_height_mm: 122.88, machine_z_mm: 200.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PWMB: AffMachineProfile = AffMachineProfile {
    key_suffix: "pwmb", machine_name: "Photon Mono X 6K / M3 Plus", max_version: 517,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 198.15, display_height_mm: 123.84, machine_z_mm: 245.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PX6S: AffMachineProfile = AffMachineProfile {
    key_suffix: "px6s", machine_name: "Photon Mono X 6Ks", max_version: 517,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 195.84, display_height_mm: 122.40, machine_z_mm: 200.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PMSQ: AffMachineProfile = AffMachineProfile {
    key_suffix: "pmsq", machine_name: "Photon Mono SQ", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 128.0, display_height_mm: 120.0, machine_z_mm: 200.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PM3: AffMachineProfile = AffMachineProfile {
    key_suffix: "pm3", machine_name: "Photon M3", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 163.84, display_height_mm: 102.40, machine_z_mm: 180.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PM3M: AffMachineProfile = AffMachineProfile {
    key_suffix: "pm3m", machine_name: "Photon M3 Max", max_version: 516,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 298.08, display_height_mm: 165.60, machine_z_mm: 300.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PM3R: AffMachineProfile = AffMachineProfile {
    key_suffix: "pm3r", machine_name: "Photon M3 Premium", max_version: 517,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 218.88, display_height_mm: 123.12, machine_z_mm: 250.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PM5: AffMachineProfile = AffMachineProfile {
    key_suffix: "pm5", machine_name: "Photon Mono M5", max_version: 517,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 218.88, display_height_mm: 122.88, machine_z_mm: 200.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_PM5S: AffMachineProfile = AffMachineProfile {
    key_suffix: "pm5s", machine_name: "Photon Mono M5s", max_version: 518,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 218.88, display_height_mm: 122.88, machine_z_mm: 200.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

const PROFILE_M5SP: AffMachineProfile = AffMachineProfile {
    key_suffix: "m5sp", machine_name: "Photon Mono M5s Pro", max_version: 518,
    rle_format: AffRleFormat::Pw0,
    display_width_mm: 223.6416, display_height_mm: 126.976, machine_z_mm: 200.0,
    default_pixel_um: 47.25, layer_image_format: "pw0Img",
    preview_size: [224, 168], preview2_size: [330, 190],
};

pub(super) fn machine_profile_for_suffix(suffix: &str) -> &'static AffMachineProfile {
    match suffix.to_ascii_lowercase().as_str() {
        "pws"  => &PROFILE_PWS,
        "pw0"  => &PROFILE_PW0,
        "pwx"  => &PROFILE_PWX,
        "dlp"  => &PROFILE_DLP,
        "dl2p" => &PROFILE_DL2P,
        "pwmo" => &PROFILE_PWMO,
        "pm3n" => &PROFILE_PM3N,
        "pm4n" => &PROFILE_PM4N,
        "pwms" => &PROFILE_PWMS,
        "pwma" => &PROFILE_PWMA,
        "pwmx" => &PROFILE_PWMX,
        "pmx2" => &PROFILE_PMX2,
        "pwmb" => &PROFILE_PWMB,
        "px6s" => &PROFILE_PX6S,
        "pmsq" => &PROFILE_PMSQ,
        "pm3"  => &PROFILE_PM3,
        "pm3m" => &PROFILE_PM3M,
        "pm3r" => &PROFILE_PM3R,
        "pm5"  => &PROFILE_PM5,
        "pm5s" => &PROFILE_PM5S,
        "m5sp" => &PROFILE_M5SP,
        _other  => {
            // Unknown key suffix — default to Photon Mono profile.
            &PROFILE_PWMO
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_aff_extension_resolves_to_distinct_profile() {
        let suffixes = [
            "pws","pw0","pwx","dlp","dl2p","pwmo","pm3n","pm4n","pwms","pwma",
            "pwmx","pmx2","pwmb","px6s","pmsq","pm3","pm3m","pm3r","pm5","pm5s","m5sp",
        ];
        for s in suffixes {
            let p = machine_profile_for_suffix(s);
            assert_eq!(p.key_suffix, s, "suffix {s} -> profile.key_suffix mismatch");
        }
    }

    #[test]
    fn unknown_suffix_falls_back_to_mono() {
        let p = machine_profile_for_suffix("nope");
        assert_eq!(p.key_suffix, "pwmo");
    }

    #[test]
    fn pws_uses_pws_rle_format() {
        assert!(matches!(machine_profile_for_suffix("pws").rle_format, AffRleFormat::Pws));
    }

    #[test]
    fn pw0_extensions_use_pw0_rle_format() {
        for s in ["pw0", "pm3m", "pm5s", "m5sp", "dlp"] {
            assert!(matches!(machine_profile_for_suffix(s).rle_format, AffRleFormat::Pw0),
                "{s} should use PW0");
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Timing & build models
// ═══════════════════════════════════════════════════════════════════

pub(super) const MM_MIN_TO_MM_SEC: f32 = 1.0 / 60.0;

#[derive(Debug, Clone)]
pub(super) struct AffTimingModel {
    pub normal_exposure_sec: f32,
    pub bottom_exposure_sec: f32,
    pub bottom_layer_count: u32,
    pub layer_height_mm: f32,
    pub wait_time_before_cure_sec: f32,

    // Stage 1 (slow) — used as the legacy LiftHeight/LiftSpeed when v < 516
    pub lift_height_mm: f32,
    pub lift_speed_mm_s: f32,
    pub retract_speed_mm_s: f32,

    // Stage 2 (fast) — only used for v >= 516
    pub lift_height2_mm: f32,
    pub lift_speed2_mm_s: f32,
    pub retract_speed2_mm_s: f32,

    pub bottom_lift_height_mm: f32,
    pub bottom_lift_speed_mm_s: f32,
    pub bottom_retract_speed_mm_s: f32,
    pub bottom_lift_height2_mm: f32,
    pub bottom_lift_speed2_mm_s: f32,
    pub bottom_retract_speed2_mm_s: f32,

    pub transition_layer_count: u32,
    pub anti_alias_level: u32,
}

#[derive(Debug, Clone)]
pub(super) struct AffBuildModel {
    pub machine_name: String,
    pub display_width_mm: f32,
    pub display_height_mm: f32,
    pub machine_z_mm: f32,
    pub pixel_width_um: f32,
    pub pixel_height_um: f32,
    pub key_suffix: String,
    pub resin_volume_ml: f32,
    pub resin_density: f32,
    pub resin_price: f32,
}

// ── JSON helpers (duplicate of afz_metadata's — keep modules independent) ──

fn parse_json(metadata_json: &str) -> Option<Value> {
    serde_json::from_str::<Value>(metadata_json).ok()
}

fn get_f32(v: &Value, key: &str) -> Option<f32> {
    v.get(key).and_then(Value::as_f64).map(|v| v as f32)
}

fn get_u32(v: &Value, key: &str) -> Option<u32> {
    v.get(key).and_then(Value::as_u64).map(|v| v as u32)
}

fn get_str<'a>(v: &'a Value, key: &str) -> Option<&'a str> {
    v.get(key).and_then(Value::as_str)
}

fn sanitize_non_negative(v: f32) -> f32 {
    if v.is_finite() && v >= 0.0 { v } else { 0.0 }
}

pub(super) fn parse_aff_timing_model(job: &SliceJobV3) -> AffTimingModel {
    let meta = parse_json(&job.metadata_json);
    let material = meta.as_ref().and_then(|m| m.get("material"));
    let anycubic = meta.as_ref().and_then(|m| m.get("anycubic"));
    let printer = meta.as_ref().and_then(|m| m.get("printer"));

    let settings_mode = printer
        .and_then(|p| get_str(p, "settingsMode"))
        .unwrap_or("simple");
    let twostage = settings_mode.eq_ignore_ascii_case("twostage");

    let f = |section: Option<&Value>, key: &str| -> Option<f32> {
        section.and_then(|s| get_f32(s, key)).map(sanitize_non_negative)
    };

    let speed = |section: Option<&Value>, key: &str, default_mm_min: f32| -> f32 {
        sanitize_non_negative(
            section
                .and_then(|s| get_f32(s, key))
                .unwrap_or(default_mm_min)
                * MM_MIN_TO_MM_SEC,
        )
    };

    let bottom_layer_count = material
        .and_then(|m| get_u32(m, "bottomLayerCount"))
        .unwrap_or(4);
    let normal_exposure = f(material, "normalExposureSec").unwrap_or(2.0);
    let bottom_exposure = f(material, "bottomExposureSec").unwrap_or(30.0);
    let wait_time = f(material, "waitTimeBeforeCureSec")
        .or_else(|| f(material, "lightOffDelaySec"))
        .unwrap_or(0.5);

    let lift_height = f(material, "liftDistanceMm").unwrap_or(5.0);
    let lift_height2 = f(material, "liftDistance2Mm").unwrap_or(0.0);
    let bottom_lift_height = f(material, "bottomLiftDistanceMm").unwrap_or(5.0);
    let bottom_lift_height2 = f(material, "bottomLiftDistance2Mm").unwrap_or(0.0);

    let lift_speed = speed(material, "liftSpeedMmMin", 120.0);
    let lift_speed2 = speed(material, "liftSpeed2MmMin", 360.0);
    let retract_speed = speed(material, "retractSpeedMmMin", 120.0);
    let retract_speed2 = speed(material, "retractSpeed2MmMin", 360.0);
    let bottom_lift_speed = speed(material, "bottomLiftSpeedMmMin", 120.0);
    let bottom_lift_speed2 = speed(material, "bottomLiftSpeed2MmMin", 180.0);
    let bottom_retract_speed = speed(material, "bottomRetractSpeedMmMin", 120.0);
    let bottom_retract_speed2 = speed(material, "bottomRetractSpeed2MmMin", 180.0);

    let transition_layer_count = material
        .and_then(|m| get_u32(m, "transitionLayerCount"))
        .or_else(|| anycubic.and_then(|a| get_u32(a, "transitionLayerCount")))
        .unwrap_or(0);

    let aa_level = anycubic
        .and_then(|a| get_u32(a, "antiAliasLevel"))
        .unwrap_or(1);

    AffTimingModel {
        normal_exposure_sec: normal_exposure,
        bottom_exposure_sec: bottom_exposure,
        bottom_layer_count,
        layer_height_mm: sanitize_non_negative(job.layer_height_mm),
        wait_time_before_cure_sec: wait_time,
        lift_height_mm: lift_height,
        lift_speed_mm_s: lift_speed,
        retract_speed_mm_s: retract_speed,
        lift_height2_mm: if twostage { lift_height2 } else { 0.0 },
        lift_speed2_mm_s: if twostage { lift_speed2 } else { 0.0 },
        retract_speed2_mm_s: if twostage { retract_speed2 } else { 0.0 },
        bottom_lift_height_mm: bottom_lift_height,
        bottom_lift_speed_mm_s: bottom_lift_speed,
        bottom_retract_speed_mm_s: bottom_retract_speed,
        bottom_lift_height2_mm: if twostage { bottom_lift_height2 } else { 0.0 },
        bottom_lift_speed2_mm_s: if twostage { bottom_lift_speed2 } else { 0.0 },
        bottom_retract_speed2_mm_s: if twostage { bottom_retract_speed2 } else { 0.0 },
        transition_layer_count,
        anti_alias_level: aa_level.clamp(1, 16),
    }
}

pub(super) fn parse_aff_build_model(job: &SliceJobV3) -> AffBuildModel {
    let meta = parse_json(&job.metadata_json);
    let anycubic = meta.as_ref().and_then(|m| m.get("anycubic"));
    let printer = meta.as_ref().and_then(|m| m.get("printer"));
    let build_volume = printer.and_then(|p| p.get("buildVolumeMm"));

    // Prefer format_version from the job (set by printer profile display.formatVersion),
    // falling back to printer.formatVersion in metadata, then the legacy
    // anycubic.keySuffix metadata field for backward compatibility.
    let key_suffix = job
        .format_version
        .as_deref()
        .filter(|v| !v.is_empty())
        .or_else(|| printer.and_then(|p| get_str(p, "formatVersion")))
        .or_else(|| anycubic.and_then(|a| get_str(a, "keySuffix")))
        .unwrap_or("pwmo")
        .to_string();

    let profile = machine_profile_for_suffix(&key_suffix);

    let machine_name = anycubic
        .and_then(|a| get_str(a, "machineName"))
        .or_else(|| printer.and_then(|p| get_str(p, "machineName")))
        .unwrap_or(profile.machine_name)
        .to_string();

    let display_width = build_volume
        .and_then(|v| get_f32(v, "width"))
        .unwrap_or(profile.display_width_mm);
    let display_height = build_volume
        .and_then(|v| get_f32(v, "depth"))
        .unwrap_or(profile.display_height_mm);
    let machine_z = build_volume
        .and_then(|v| get_f32(v, "height"))
        .unwrap_or(profile.machine_z_mm);

    let pixel_size = printer.and_then(|p| p.get("pixelSize"));
    let pixel_width_um = pixel_size
        .and_then(|ps| get_f32(ps, "x"))
        .unwrap_or(profile.default_pixel_um);
    let pixel_height_um = pixel_size
        .and_then(|ps| get_f32(ps, "y"))
        .unwrap_or(profile.default_pixel_um);

    let resin_volume_ml = anycubic.and_then(|a| get_f32(a, "resinVolumeMl")).unwrap_or(1000.0);
    let resin_density = anycubic.and_then(|a| get_f32(a, "resinDensity")).unwrap_or(1.2);
    let resin_price = anycubic.and_then(|a| get_f32(a, "resinPrice")).unwrap_or(25.0);

    AffBuildModel {
        machine_name,
        display_width_mm: display_width,
        display_height_mm: display_height,
        machine_z_mm: machine_z,
        pixel_width_um,
        pixel_height_um,
        key_suffix,
        resin_volume_ml,
        resin_density,
        resin_price,
    }
}

#[cfg(test)]
mod parser_tests {
    use super::*;

    fn make_job(metadata: &str) -> SliceJobV3 {
        make_job_with_version(metadata, None)
    }

    fn make_job_with_version(metadata: &str, format_version: Option<&str>) -> SliceJobV3 {
        SliceJobV3 {
            output_format: ".aff".to_string(),
            format_version: format_version.map(|v| v.to_string()),
            source_width_px: 4,
            source_height_px: 4,
            width_px: 4,
            height_px: 4,
            build_width_mm: 10.0,
            build_depth_mm: 20.0,
            layer_height_mm: 0.05,
            total_layers: 1,
            export_thumbnail_png_base64: None,
            png_compression_strategy: "balanced".to_string(),
            container_compression_level: 2,
            anti_aliasing_level: "Off".to_string(),
            aa_on_supports: false,
            minimum_aa_alpha_percent: 35.0,
            mirror_x: false,
            mirror_y: false,
            triangles_xyz: vec![],
            metadata_json: metadata.to_string(),
            x_packing_mode: "none".to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn build_model_reads_format_version_primary() {
        let job = make_job_with_version("{}", Some("pm5s"));
        let build = parse_aff_build_model(&job);
        assert_eq!(build.key_suffix, "pm5s");
        assert_eq!(build.machine_name, "Photon Mono M5s");
    }

    #[test]
    fn build_model_format_version_takes_priority_over_keysuffix() {
        // When both format_version and anycubic.keySuffix are present,
        // format_version must win.
        let job = make_job_with_version(
            r#"{"anycubic":{"keySuffix":"pwmo"}}"#,
            Some("pm3m"),
        );
        let build = parse_aff_build_model(&job);
        assert_eq!(build.key_suffix, "pm3m");
        assert_eq!(build.machine_name, "Photon M3 Max");
    }

    #[test]
    fn build_model_reads_keysuffix_from_anycubic_namespace() {
        let job = make_job(r#"{"anycubic":{"keySuffix":"pm3m"}}"#);
        let build = parse_aff_build_model(&job);
        assert_eq!(build.key_suffix, "pm3m");
        assert_eq!(build.machine_name, "Photon M3 Max");
    }

    #[test]
    fn build_model_falls_back_to_printer_format_version() {
        let job = make_job(r#"{"printer":{"formatVersion":"dl2p"}}"#);
        let build = parse_aff_build_model(&job);
        assert_eq!(build.key_suffix, "dl2p");
        assert_eq!(build.machine_name, "Photon D2");
    }

    #[test]
    fn build_model_ignores_printer_name_for_machine_name() {
        // The raster manifest's printer.name is a user-customizable display name.
        // The machine name written into the file must be the canonical hardware name
        // from the profile constant, otherwise firmware may reject the file.
        let job = make_job(r#"{"printer":{"name":"My Custom Printer","formatVersion":"pm5"}}"#);
        let build = parse_aff_build_model(&job);
        assert_eq!(build.key_suffix, "pm5");
        assert_eq!(build.machine_name, "Photon Mono M5"); // canonical, not "My Custom Printer"
    }

    #[test]
    fn build_model_uses_profile_default_when_keysuffix_absent() {
        let job = make_job("{}");
        let build = parse_aff_build_model(&job);
        assert_eq!(build.key_suffix, "pwmo");
        assert_eq!(build.machine_name, "Photon Mono");
    }

    #[test]
    fn timing_model_converts_mm_min_to_mm_sec() {
        let job = make_job(r#"{"material":{"liftSpeedMmMin":120}}"#);
        let timing = parse_aff_timing_model(&job);
        assert!((timing.lift_speed_mm_s - 2.0).abs() < 1e-6, "got {}", timing.lift_speed_mm_s);
    }

    #[test]
    fn timing_model_clamps_aa_level_to_1_16() {
        let job_low = make_job(r#"{"anycubic":{"antiAliasLevel":0}}"#);
        assert_eq!(parse_aff_timing_model(&job_low).anti_alias_level, 1);

        let job_high = make_job(r#"{"anycubic":{"antiAliasLevel":99}}"#);
        assert_eq!(parse_aff_timing_model(&job_high).anti_alias_level, 16);
    }
}
