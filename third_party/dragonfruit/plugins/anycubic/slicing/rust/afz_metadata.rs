//! Metadata parsing for the AFZ (Anycubic Zip Format) encoder.
//!
//! Extracts timing, machine, and resin parameters from `job.metadata_json`
//! to populate the JSON manifests and binary scene file inside the ZIP.

use crate::types::SliceJobV3;
use serde_json::Value;

/// Speed unit used by AFZ format is mm/s; the slicer job uses mm/min.
pub(super) const MM_MIN_TO_MM_SEC: f32 = 1.0 / 60.0;

// ═══════════════════════════════════════════════════════════════════
//  Per-printer machine profile
// ═══════════════════════════════════════════════════════════════════

/// Hardware and firmware constants that vary per Anycubic printer model.
/// These are embedded into the `anycubic_photon_resins.pwsp` JSON manifest
/// and must match what Anycubic Photon Workshop expects for each printer.
#[derive(Debug, Clone)]
pub(super) struct AfzMachineProfile {
    /// Canonical machine name (e.g. "Anycubic Photon Mono M7 Max").
    pub machine_name: &'static str,
    /// Picture filename used in the manifest (e.g. "Anycubic_Photon_Mono_M7Max.png").
    pub picture: &'static str,
    /// Pixel pitch X in microns.
    pub pixel_pitch_x_um: f32,
    /// Pixel pitch Y in microns (may differ from X for non-square pixel panels).
    pub pixel_pitch_y_um: f32,
    /// Display width in mm.
    pub print_x_mm: f32,
    /// Display height in mm.
    pub print_y_mm: f32,
    /// Maximum build height in mm.
    pub print_z_mm: f32,
    /// Rotation around Z axis (0.0 or 180.0).
    pub rotate_z: f32,
    /// Raster segments capacity (0 or 100000).
    pub raster_segments_capacity: u32,
    /// Z-axis max acceleration for firmware time calculation.
    pub machine_max_acceleration_z: u32,
    /// Maximum file format version accepted by this printer's firmware.
    pub max_file_version: u32,
    /// Preview 1 dimensions [width, height].
    pub prev1_size: [u32; 2],
    /// Preview 2 dimensions [width, height].
    pub prev2_size: [u32; 2],
    /// Cloud preview dimensions [width, height].
    pub cloud_prev_size: [u32; 2],
}

const PROFILE_PM7M: AfzMachineProfile = AfzMachineProfile {
    machine_name: "Anycubic Photon Mono M7 Max",
    picture: "Anycubic_Photon_Mono_M7Max.png",
    pixel_pitch_x_um: 46.0,
    pixel_pitch_y_um: 46.0,
    print_x_mm: 297.5,
    print_y_mm: 164.0,
    print_z_mm: 300.0,
    rotate_z: 0.0,
    raster_segments_capacity: 0,
    machine_max_acceleration_z: 20,
    max_file_version: 518,
    prev1_size: [224, 168],
    prev2_size: [336, 252],
    cloud_prev_size: [800, 600],
};

const PROFILE_PWSZ: AfzMachineProfile = AfzMachineProfile {
    machine_name: "Anycubic Photon Mono M7 Pro",
    picture: "Anycubic_Photon_Mono_M7Pro.png",
    pixel_pitch_x_um: 16.8,
    pixel_pitch_y_um: 24.8,
    print_x_mm: 223.642,
    print_y_mm: 126.48,
    print_z_mm: 230.0,
    rotate_z: 0.0,
    raster_segments_capacity: 100000,
    machine_max_acceleration_z: 20,
    max_file_version: 518,
    prev1_size: [224, 168],
    prev2_size: [336, 252],
    cloud_prev_size: [800, 600],
};

const PROFILE_PM7: AfzMachineProfile = AfzMachineProfile {
    machine_name: "Anycubic Photon Mono M7",
    picture: "Anycubic_Photon_Mono_M7.png",
    pixel_pitch_x_um: 16.8,
    pixel_pitch_y_um: 24.8,
    print_x_mm: 223.642,
    print_y_mm: 126.48,
    print_z_mm: 230.0,
    rotate_z: 0.0,
    raster_segments_capacity: 100000,
    machine_max_acceleration_z: 20,
    max_file_version: 518,
    prev1_size: [168, 126],
    prev2_size: [168, 126],
    cloud_prev_size: [800, 600],
};

const PROFILE_PM4U: AfzMachineProfile = AfzMachineProfile {
    machine_name: "Anycubic Photon Mono 4 Ultra",
    picture: "Anycubic_Photon_Mono_M4Ultra.png",
    pixel_pitch_x_um: 17.0,
    pixel_pitch_y_um: 17.0,
    print_x_mm: 153.408,
    print_y_mm: 87.04,
    print_z_mm: 165.0,
    rotate_z: 180.0,
    raster_segments_capacity: 100000,
    machine_max_acceleration_z: 20,
    max_file_version: 518,
    prev1_size: [168, 126],
    prev2_size: [168, 126],
    cloud_prev_size: [800, 600],
};

const PROFILE_PP1: AfzMachineProfile = AfzMachineProfile {
    machine_name: "Anycubic Photon P1",
    picture: "Anycubic_Photon_P1.png",
    pixel_pitch_x_um: 18.0,
    pixel_pitch_y_um: 18.0,
    print_x_mm: 223.0,
    print_y_mm: 126.0,
    print_z_mm: 230.0,
    rotate_z: 0.0,
    raster_segments_capacity: 100000,
    machine_max_acceleration_z: 20,
    max_file_version: 519,
    prev1_size: [224, 168],
    prev2_size: [336, 252],
    cloud_prev_size: [800, 600],
};

const PROFILE_PP1M: AfzMachineProfile = AfzMachineProfile {
    machine_name: "Anycubic Photon P1 Max",
    picture: "Anycubic_Photon_P1Max.png",
    pixel_pitch_x_um: 18.0,
    pixel_pitch_y_um: 18.0,
    print_x_mm: 297.5,
    print_y_mm: 164.0,
    print_z_mm: 300.0,
    rotate_z: 0.0,
    raster_segments_capacity: 100000,
    machine_max_acceleration_z: 20,
    max_file_version: 519,
    prev1_size: [224, 168],
    prev2_size: [336, 252],
    cloud_prev_size: [800, 600],
};

/// Look up the machine profile for a given key_suffix.
/// Falls back to PM7M profile for unknown suffixes.
pub(super) fn machine_profile_for_suffix(suffix: &str) -> &'static AfzMachineProfile {
    match suffix {
        "pm7m" => &PROFILE_PM7M,
        "pwsz" => &PROFILE_PWSZ,
        "pm7" => &PROFILE_PM7,
        "pm4u" => &PROFILE_PM4U,
        "pp1" => &PROFILE_PP1,
        "pp1m" => &PROFILE_PP1M,
        _ => &PROFILE_PM7M,
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Timing model
// ═══════════════════════════════════════════════════════════════════

/// Parsed timing/lift model from metadata JSON.
#[derive(Debug, Clone)]
pub(super) struct AfzTimingModel {
    pub normal_exposure_sec: f32,
    pub bottom_exposure_sec: f32,
    pub bottom_layer_count: u32,
    pub layer_height_mm: f32,
    pub wait_time_before_cure_sec: f32,

    // Stage 1 (slow/short)
    pub bottom_lift_height_mm: f32,
    pub bottom_lift_speed_mm_s: f32,
    pub bottom_retract_speed_mm_s: f32,

    // Stage 2 (fast/long)
    pub bottom_lift_height2_mm: f32,
    pub bottom_lift_speed2_mm_s: f32,
    pub bottom_retract_speed2_mm_s: f32,

    // Normal stage 1
    pub lift_height_mm: f32,
    pub lift_speed_mm_s: f32,
    pub retract_speed_mm_s: f32,

    // Normal stage 2
    pub lift_height2_mm: f32,
    pub lift_speed2_mm_s: f32,
    pub retract_speed2_mm_s: f32,

    pub transition_layer_count: u32,
    pub anti_alias_level: u32,
    pub twostage: bool,
}

// ═══════════════════════════════════════════════════════════════════
//  Build model
// ═══════════════════════════════════════════════════════════════════

/// Machine/resin identity extracted from metadata.
#[derive(Debug, Clone)]
pub(super) struct AfzBuildModel {
    pub machine_name: String,
    pub display_width_mm: f32,
    pub display_height_mm: f32,
    pub machine_z_mm: f32,
    pub pixel_width_um: f32,
    pub pixel_height_um: f32,
    pub resin_type: String,
    pub resin_density: f32,
    pub resin_price: f32,
    pub resin_volume_ml: f32,
    pub key_suffix: String,
    // v4 resin property fields
    pub resin_brand_name: String,
    pub resin_resin_name: String,
    pub resin_film_name: String,
    pub resin_setting_name: String,
    pub target_temperature: f32,
    pub intelligent_release: bool,
}

// ═══════════════════════════════════════════════════════════════════
//  JSON helpers
// ═══════════════════════════════════════════════════════════════════

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

fn get_bool(v: &Value, key: &str) -> Option<bool> {
    v.get(key).and_then(Value::as_bool)
}

// ═══════════════════════════════════════════════════════════════════
//  Parsers
// ═══════════════════════════════════════════════════════════════════

fn sanitize_non_negative(v: f32) -> f32 {
    if v.is_finite() && v >= 0.0 { v } else { 0.0 }
}

/// Extract the AFZ timing model from `job.metadata_json`.
///
/// Looks under `metadata_json.material.*` for timing values (same as CTB),
/// and under `metadata_json.anycubic.*` for AFZ-specific overrides.
pub(super) fn parse_afz_timing_model(job: &SliceJobV3) -> AfzTimingModel {
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

    let bottom_layer_count = material
        .and_then(|m| get_u32(m, "bottomLayerCount"))
        .unwrap_or(4);

    let normal_exposure = f(material, "normalExposureSec").unwrap_or(2.0);
    let bottom_exposure = f(material, "bottomExposureSec").unwrap_or(30.0);

    let wait_time = f(material, "waitTimeBeforeCureSec")
        .or_else(|| f(material, "lightOffDelaySec"))
        .unwrap_or(0.5);

    // Speeds in metadata are mm/min; AFZ needs mm/s
    let speed = |section: Option<&Value>, key: &str, default_mm_min: f32| -> f32 {
        sanitize_non_negative(
            section
                .and_then(|s| get_f32(s, key))
                .unwrap_or(default_mm_min)
                * MM_MIN_TO_MM_SEC,
        )
    };

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
        .unwrap_or(4);

    AfzTimingModel {
        normal_exposure_sec: normal_exposure,
        bottom_exposure_sec: bottom_exposure,
        bottom_layer_count,
        layer_height_mm: sanitize_non_negative(job.layer_height_mm),
        wait_time_before_cure_sec: wait_time,
        bottom_lift_height_mm: bottom_lift_height,
        bottom_lift_speed_mm_s: bottom_lift_speed,
        bottom_retract_speed_mm_s: bottom_retract_speed,
        bottom_lift_height2_mm: bottom_lift_height2,
        bottom_lift_speed2_mm_s: bottom_lift_speed2,
        bottom_retract_speed2_mm_s: bottom_retract_speed2,
        lift_height_mm: lift_height,
        lift_speed_mm_s: lift_speed,
        retract_speed_mm_s: retract_speed,
        lift_height2_mm: lift_height2,
        lift_speed2_mm_s: lift_speed2,
        retract_speed2_mm_s: retract_speed2,
        transition_layer_count,
        anti_alias_level: aa_level.clamp(1, 16),
        twostage,
    }
}

/// Extract the AFZ build/machine model from the job.
pub(super) fn parse_afz_build_model(job: &SliceJobV3) -> AfzBuildModel {
    let meta = parse_json(&job.metadata_json);
    let anycubic = meta.as_ref().and_then(|m| m.get("anycubic"));
    let material = meta.as_ref().and_then(|m| m.get("material"));
    let printer = meta.as_ref().and_then(|m| m.get("printer"));
    let build_volume = printer.and_then(|p| p.get("buildVolumeMm"));

    let settings_mode = printer
        .and_then(|p| get_str(p, "settingsMode"))
        .unwrap_or("simple");
    let twostage = settings_mode.eq_ignore_ascii_case("twostage");

    // Derive the machine key suffix from the most specific source available:
    // 1. `job.format_version` (set by printer profile display.formatVersion) — preferred
    // 2. `printer.formatVersion` in metadata (set by the raster manifest)
    // 3. Explicit `anycubic.keySuffix` override in metadata (legacy fallback)
    // 4. Printer output format extension from the selected printer profile
    //    (e.g. ".pwsz" → "pwsz", ".pm7m" → "pm7m")
    // 5. Fall back to "pm7m" only when none of the above are present
    let key_suffix = job
        .format_version
        .as_deref()
        .filter(|v| !v.is_empty())
        .or_else(|| printer.and_then(|p| get_str(p, "formatVersion")))
        .or_else(|| anycubic.and_then(|a| get_str(a, "keySuffix")))
        .or_else(|| {
            printer
                .and_then(|p| get_str(p, "outputFormat"))
                .map(|s| s.trim_start_matches('.'))
        })
        .unwrap_or("pm7m")
        .to_string();

    let profile = machine_profile_for_suffix(&key_suffix);

    // Read machine name from metadata, falling back through available keys:
    // 1. anycubic.machineName (explicit override)
    // 2. printer.machineName (canonical metadata key)
    // 3. Profile constant derived from key_suffix (ensures firmware-compatible name)
    let machine_name = anycubic
        .and_then(|a| get_str(a, "machineName"))
        .or_else(|| printer.and_then(|p| get_str(p, "machineName")))
        .unwrap_or(profile.machine_name)
        .to_string();

    let display_width = build_volume
        .and_then(|v| get_f32(v, "width"))
        .unwrap_or(profile.print_x_mm);
    let display_height = build_volume
        .and_then(|v| get_f32(v, "depth"))
        .unwrap_or(profile.print_y_mm);
    let machine_z = build_volume
        .and_then(|v| get_f32(v, "height"))
        .unwrap_or(profile.print_z_mm);

    let pixel_size = printer.and_then(|p| p.get("pixelSize"));
    let pixel_width_um = pixel_size
        .and_then(|ps| get_f32(ps, "x"))
        .or_else(|| anycubic.and_then(|a| get_f32(a, "pixelWidthUm")))
        .unwrap_or(profile.pixel_pitch_x_um);
    let pixel_height_um = pixel_size
        .and_then(|ps| get_f32(ps, "y"))
        .or_else(|| anycubic.and_then(|a| get_f32(a, "pixelHeightUm")))
        .unwrap_or(profile.pixel_pitch_y_um);

    let resin_brand_name = anycubic
        .and_then(|a| get_str(a, "resinBrandName"))
        .unwrap_or("Generic")
        .to_string();
    let resin_resin_name = anycubic
        .and_then(|a| get_str(a, "resinResinName"))
        .unwrap_or("standard_resin")
        .to_string();
    let resin_film_name = anycubic
        .and_then(|a| get_str(a, "resinFilmName"))
        .unwrap_or("ACF")
        .to_string();
    let resin_setting_name = anycubic
        .and_then(|a| get_str(a, "resinSettingName"))
        .unwrap_or("default")
        .to_string();
    let resin_type = anycubic
        .and_then(|a| get_str(a, "resinType"))
        .unwrap_or("Standard resin")
        .to_string();
    let resin_density = anycubic
        .and_then(|a| get_f32(a, "resinDensity"))
        .unwrap_or(1.2);
    let resin_price = anycubic
        .and_then(|a| get_f32(a, "resinPrice"))
        .unwrap_or(25.0);
    let resin_volume_ml = anycubic
        .and_then(|a| get_f32(a, "resinVolumeMl"))
        .unwrap_or(1000.0);

    let target_temperature = material
        .and_then(|m| get_f32(m, "targetTemperatureC"))
        .unwrap_or(25.0);

    let intelligent_release = !twostage
        && material
            .and_then(|m| get_bool(m, "intelligentRelease"))
            .unwrap_or(false);

    AfzBuildModel {
        machine_name,
        display_width_mm: display_width,
        display_height_mm: display_height,
        machine_z_mm: machine_z,
        pixel_width_um,
        pixel_height_um,
        resin_type,
        resin_density,
        resin_price,
        resin_volume_ml,
        key_suffix,
        resin_brand_name,
        resin_resin_name,
        resin_film_name,
        resin_setting_name,
        target_temperature,
        intelligent_release,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_job(metadata: &str) -> SliceJobV3 {
        make_job_with_version(metadata, None)
    }

    fn make_job_with_version(metadata: &str, format_version: Option<&str>) -> SliceJobV3 {
        SliceJobV3 {
            output_format: ".azf".to_string(),
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
        let job = make_job_with_version("{}", Some("pm4u"));
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pm4u");
        assert_eq!(build.machine_name, "Anycubic Photon Mono 4 Ultra");
    }

    #[test]
    fn build_model_format_version_takes_priority_over_keysuffix() {
        let job = make_job_with_version(r#"{"anycubic":{"keySuffix":"pm7m"}}"#, Some("pm4u"));
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pm4u");
        assert_eq!(build.machine_name, "Anycubic Photon Mono 4 Ultra");
    }

    #[test]
    fn build_model_falls_back_to_printer_format_version() {
        let job = make_job(r#"{"printer":{"formatVersion":"pwsz"}}"#);
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pwsz");
        assert_eq!(build.machine_name, "Anycubic Photon Mono M7 Pro");
    }

    #[test]
    fn build_model_falls_back_to_keysuffix() {
        let job = make_job(r#"{"anycubic":{"keySuffix":"pm4u"}}"#);
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pm4u");
    }

    #[test]
    fn build_model_falls_back_to_printer_output_format() {
        let job = make_job(r#"{"printer":{"outputFormat":".pwsz"}}"#);
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pwsz");
        assert_eq!(build.machine_name, "Anycubic Photon Mono M7 Pro");
    }

    #[test]
    fn build_model_uses_default_when_nothing_set() {
        let job = make_job("{}");
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pm7m");
    }

    #[test]
    fn build_model_resolves_pp1_from_format_version() {
        let job = make_job_with_version("{}", Some("pp1"));
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pp1");
        assert_eq!(build.machine_name, "Anycubic Photon P1");
    }

    #[test]
    fn pp1_profile_has_bumped_max_file_version() {
        let profile = machine_profile_for_suffix("pp1");
        assert_eq!(profile.max_file_version, 519);
    }

    #[test]
    fn build_model_resolves_pp1m_from_format_version() {
        let job = make_job_with_version("{}", Some("pp1m"));
        let build = parse_afz_build_model(&job);
        assert_eq!(build.key_suffix, "pp1m");
        assert_eq!(build.machine_name, "Anycubic Photon P1 Max");
    }

    #[test]
    fn pp1m_profile_has_bumped_max_file_version() {
        let profile = machine_profile_for_suffix("pp1m");
        assert_eq!(profile.max_file_version, 519);
    }

    #[test]
    fn existing_profiles_keep_max_file_version_518() {
        for suffix in ["pm7m", "pwsz", "pm7", "pm4u"] {
            let profile = machine_profile_for_suffix(suffix);
            assert_eq!(profile.max_file_version, 518, "{} should have max_file_version 518", suffix);
        }
    }
}
