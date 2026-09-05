//! AFZ (Anycubic Zip Format) container assembly.
//!
//! Builds a ZIP archive containing:
//! - `anycubic_photon_resins.pwsp` — machine + resin settings (JSON)
//! - `layers_controller.conf` — per-layer parameters (JSON)
//! - `print_info.json` — cost/time/volume summary (JSON)
//! - `software_info.conf` — software identification (JSON)
//! - `scene.slice` — binary scene header + per-layer bounding data
//! - `preview_images/preview_0.png` — large thumbnail
//! - `preview_images/preview_1.png` — small thumbnail
//! - `layer_images/layer_N.pw0Img` — PW0 RLE encoded layer images

use crate::engine::SlicerV3Error;
use crate::types::{LayerAreaStatsV3, SliceJobV3};

use super::afz_metadata::{AfzBuildModel, AfzMachineProfile, AfzTimingModel};
use super::afz_preview;
use std::io::{Cursor, Write};
use zip::write::FileOptions;
use zip::ZipWriter;

// ── JSON manifest file names ────────────────────────────────────────
const SETTINGS_FILE: &str = "anycubic_photon_resins.pwsp";
const LAYERS_FILE: &str = "layers_controller.conf";
const PRINT_INFO_FILE: &str = "print_info.json";
const SOFTWARE_INFO_FILE: &str = "software_info.conf";
const LCD_FUNCTION_FILE: &str = "lcd_function.json";
const SCENE_FILE: &str = "scene.slice";

// ── Scene binary constants ──────────────────────────────────────────
const SCENE_MAGIC: &[u8; 16] = b"ANYCUBIC-PWSZ\0\0\0";
const SCENE_SOFTWARE_LEN: usize = 64;
const SCENE_PADDING_U32S: usize = 64;
const SCENE_LAYER_DEF_PADDING_U32S: usize = 8;

/// A prepared (PW0-encoded) layer ready for writing into the ZIP.
pub(super) struct AfzPreparedLayer {
    pub index: usize,
    pub encoded: Vec<u8>,
    pub non_zero_pixel_count: u32,
}

/// Build the complete AFZ ZIP container as an in-memory byte vector.
pub(super) fn build_afz_container(
    job: &SliceJobV3,
    timing: &AfzTimingModel,
    build: &AfzBuildModel,
    profile: &AfzMachineProfile,
    layers: &[AfzPreparedLayer],
    layer_area_stats: &[LayerAreaStatsV3],
    on_progress: Option<&dyn Fn(u32, u32)>,
) -> Result<Vec<u8>, SlicerV3Error> {
    let total_steps = (layers.len() as u32) + 4; // layers + manifests + scene + previews + done
    let mut step: u32 = 0;
    let mut advance = |steps: u32| {
        step = step.saturating_add(steps);
        if let Some(cb) = on_progress {
            cb(step, total_steps);
        }
    };

    let buf = Vec::with_capacity(4 * 1024 * 1024);
    let cursor = Cursor::new(buf);
    let mut zip = ZipWriter::new(cursor);
    let options: FileOptions =
        FileOptions::default().compression_method(zip::CompressionMethod::Deflated);

    // Build previews up front (written later in correct order)
    let preview_1 = afz_preview::build_preview_png(
        job.export_thumbnail_png_base64.as_deref(),
        profile.prev1_size[0],
        profile.prev1_size[1],
    );
    let preview_2 = afz_preview::build_preview_png(
        job.export_thumbnail_png_base64.as_deref(),
        profile.prev2_size[0],
        profile.prev2_size[1],
    );
    let preview_3 = afz_preview::build_preview_png(
        job.export_thumbnail_png_base64.as_deref(),
        profile.cloud_prev_size[0],
        profile.cloud_prev_size[1],
    );

    // ── Entry order matches Anycubic Photon Workshop ──────────────
    // 1. Settings
    let settings_json = build_settings_json(job, timing, build, profile);
    zip.start_file(SETTINGS_FILE, options)?;
    zip.write_all(settings_json.as_bytes())?;

    // 2. Print info
    let print_info_json = build_print_info_json(job, timing, build, layers, layer_area_stats);
    zip.start_file(PRINT_INFO_FILE, options)?;
    zip.write_all(print_info_json.as_bytes())?;

    // 3. Software info
    let software_json = build_software_info_json();
    zip.start_file(SOFTWARE_INFO_FILE, options)?;
    zip.write_all(software_json.as_bytes())?;

    // 4. Previews (always written — gradient fallback when no thumbnail provided)
    zip.start_file("preview_images/preview_0.png", options)?;
    zip.write_all(&preview_1)?;
    zip.start_file("preview_images/preview_1.png", options)?;
    zip.write_all(&preview_2)?;
    zip.start_file("preview_images/preview_2.png", options)?;
    zip.write_all(&preview_3)?;

    // 5. Layers controller
    let layers_json = build_layers_controller_json(timing, layers);
    zip.start_file(LAYERS_FILE, options)?;
    zip.write_all(layers_json.as_bytes())?;

    // 6. LCD function
    let lcd_json = build_lcd_function_json();
    zip.start_file(LCD_FUNCTION_FILE, options)?;
    zip.write_all(lcd_json.as_bytes())?;

    advance(1);

    // 7. Layer images
    for layer in layers {
        let name = format!("layer_images/layer_{}.pw0Img", layer.index);
        zip.start_file(&name, options)?;
        zip.write_all(&layer.encoded)?;
        advance(1);
    }

    // 8. Scene binary (last entry)
    let scene = build_scene_binary(job, timing, build, layers, layer_area_stats);
    zip.start_file(SCENE_FILE, options)?;
    zip.write_all(&scene)?;

    advance(1);

    let cursor = zip.finish()?;

    advance(1);

    Ok(cursor.into_inner())
}

// ═══════════════════════════════════════════════════════════════════
//  JSON builders
// ═══════════════════════════════════════════════════════════════════

/// Format an f32 so it always contains a decimal point in JSON output.
/// Rust's default Display for f32 omits `.0` for whole numbers (e.g. `46`),
/// but Anycubic's firmware parser is type-strict and expects floats.
fn jf(v: f32) -> String {
    let s = format!("{}", v);
    if s.contains('.') {
        s
    } else {
        format!("{}.0", s)
    }
}

fn build_settings_json(
    job: &SliceJobV3,
    timing: &AfzTimingModel,
    build: &AfzBuildModel,
    profile: &AfzMachineProfile,
) -> String {
    // Build the multi_state_paras for the resin profile.
    // Stage 0 = step 1, stage 1 = step 2 for all fields (height, up_speed, down_speed).
    let multi_state = format!(
        r#"{{
          "bott_0": {{ "height": {bh1}, "up_speed": {bus1}, "down_speed": {bds1} }},
          "bott_1": {{ "height": {bh2}, "up_speed": {bus2}, "down_speed": {bds2} }},
          "normal_0": {{ "height": {nh1}, "up_speed": {nus1}, "down_speed": {nds1} }},
          "normal_1": {{ "height": {nh2}, "up_speed": {nus2}, "down_speed": {nds2} }}
        }}"#,
        bh1 = jf(timing.bottom_lift_height_mm),
        bus1 = jf(timing.bottom_lift_speed_mm_s),
        bds1 = jf(timing.bottom_retract_speed_mm_s),
        bh2 = jf(timing.bottom_lift_height2_mm),
        bus2 = jf(timing.bottom_lift_speed2_mm_s),
        bds2 = jf(timing.bottom_retract_speed2_mm_s),
        nh1 = jf(timing.lift_height_mm),
        nus1 = jf(timing.lift_speed_mm_s),
        nds1 = jf(timing.retract_speed_mm_s),
        nh2 = jf(timing.lift_height2_mm),
        nus2 = jf(timing.lift_speed2_mm_s),
        nds2 = jf(timing.retract_speed2_mm_s),
    );

    let total_lift = timing.lift_height_mm + timing.lift_height2_mm;

    format!(
        r#"{{
  "version": "3",
  "machine_type": {{
    "version": "3",
    "name": {machine_name},
    "key_suffix": {key_suffix},
    "key_image_format": "pwszImg",
    "res_x": {res_x},
    "res_y": {res_y},
    "xy_pixel": {pixel_w},
    "xy_pixel_y": {pixel_h},
    "rotate_z": {rotate_z},
    "max_samples": 16,
    "property": 119,
    "print_xsize": {disp_w},
    "print_ysize": {disp_h},
    "print_zsize": {mach_z},
    "max_file_version": {max_file_version},
    "prev_back_color": [0.0078125, 0.28125, 0.390625],
    "prev_model_color": [0.8046875, 0.8046875, 0.8046875],
    "prev_supports_color": [0.07421875, 0.92578125, 0.9296875],
    "prev_image_size": [{prev1_w}, {prev1_h}],
    "child_screen": [{{ "x": 0, "y": 0, "width": {res_x}, "height": {res_y} }}],
    "prev2_back_color": [0.07842999696731568, 0.1058799996972084, 0.16077999770641328],
    "prev2_image_size": [{prev2_w}, {prev2_h}],
    "raster_segments_capacity": {raster_seg_cap},
    "raster_antialiasing": {aa},
    "cloudprev_back_color": [0.9333333373069763, 0.9411764740943909, 0.9647058844566345],
    "cloudprev_imag_size": [{cprev_w}, {cprev_h}]
  }},
  "machine_extern": {{
    "version": "3",
    "alias": {machine_name},
    "picture": "{picture}",
    "cloud_property": 0,
    "device_cn_code": "",
    "factory_resins": [],
    "user_resins": [{{
      "version": "2",
      "property": {{
        "version": "4",
        "code": "10",
        "currency": "\u20ac",
        "name": {resin_qualified_name},
        "price": {resin_price},
        "type": {resin_type},
        "volume": {resin_volume},
        "subfunc_code": 0,
        "density": {resin_density},
        "target_temperature": {target_temperature},
        "brand_name": {resin_brand},
        "resin_name": {resin_resin},
        "film_name": {resin_film},
        "setting_name": {resin_setting}
      }},
      "depth_penetration_curve": {{
        "zthick_min": 0.01,
        "zthick_max": 0.2,
        "light_intensity": 9000.0,
        "safety_coefficient": 1.6,
        "current_tempcurve_selector": -1,
        "temperature_coefficients": []
      }},
      "slice_extpara": {{
        "version": "3",
        "multi_state_used": {multi_state_used},
        "transition_layercount": {transition_layers},
        "transition_type": 0,
        "multi_state_paras": {multi_state},
        "exposure_compensate": 0.0,
        "intelli_mode": {intelli_mode},
        "max_acceleration": {max_acceleration},
        "separate_support_exposure_delayed": 0.0
      }},
      "slicepara": {{
        "anti_count": 1,
        "blur_level": 0,
        "bott_layers": {bottom_layers},
        "bott_time": {bottom_exposure},
        "exposure_time": {normal_exposure},
        "gray_level": 0,
        "off_time": {wait_time},
        "use_indivi_layerpara": 0,
        "use_random_erode": 0,
        "zthick": {layer_height},
        "zup_height": {total_lift},
        "zup_speed": {lift_speed},
        "zdown_speed": {retract_speed}
      }}
    }}],
    "active_resins": [{resin_qualified_name}],
    "firmware_calc_print_time": 1,
    "firmware_calc_print_time_paras": {{
      "version": "2",
      "MACHINE_AXIS_STEPS_PER_UNIT": [100.0, 100.0, 3200.0, 94.0],
      "MACHINE_BLOCK_BUFFER_SIZE": 32,
      "MACHINE_DEFAULT_ACCELERATION": 1000.0,
      "MACHINE_DEFAULT_MINSEGMENTTIME": 20000,
      "MACHINE_DEFAULT_XYJERK": 20.0,
      "MACHINE_DEFAULT_ZJERK": 0.2,
      "MACHINE_GENERATE_FRAME_TIME": 450.0,
      "MACHINE_MAX_ACCELERATION": [1000, 1000, {max_accel_z}, 1000],
      "MACHINE_MAX_FEEDRATE": [200.0, 200.0, 20.0, 45.0],
      "MACHINE_MAX_STEP_FREQUENCY": 256000,
      "MACHINE_MINIMUM_PLANNER_SPEED": 0.05,
      "MACHINE_NOR_LAYER_DOWN_HEIGHT_DIV": 0.25,
      "MACHINE_NOR_LAYER_DOWN_SPEED_DIV": 0.5,
      "MACHINE_NOR_LAYER_UP_HEIGHT_DIV": 0.25,
      "MACHINE_NOR_LAYER_UP_SPEED_DIV": 0.5,
      "MACHINE_STEP_MUL": 1,
      "MACHINE_TIME_COMPENSATE": 0.0,
      "MACHINE_TIM_PRES": 30.0,
      "MACHINE_TIM_RCC_CLK": 60.0,
      "FUNCTION": 1,
      "MACHINE_MODE_ACCELERATION": [0, 0, 0, 0],
      "LAYER_COMPENSATE": [0, 0, 0, 0],
      "HEIGHT_COMPENSATE": [0, 0, 0, 0],
      "TIMES_COMPENSATE": [0, 0, 0, 0]
    }},
    "firmware_calc_exp_time_paras": {{
      "precision_range_branch": [0.0, 5.0, 25.0],
      "precision_per_volume": 5.0,
      "precision_coeff_value": [0.024, 0.01, -0.2],
      "energy_coeff": 0.0,
      "machine_exposure_ton": 0.4
    }}
  }}
}}"#,
        machine_name = serde_json::to_string(&build.machine_name)
            .unwrap_or_else(|_| "\"Unknown\"".to_string()),
        key_suffix =
            serde_json::to_string(&build.key_suffix).unwrap_or_else(|_| "\"pwsz\"".to_string()),
        res_x = job.source_width_px,
        res_y = job.source_height_px,
        pixel_w = jf(build.pixel_width_um),
        pixel_h = jf(build.pixel_height_um),
        rotate_z = jf(profile.rotate_z),
        disp_w = jf(build.display_width_mm),
        disp_h = jf(build.display_height_mm),
        mach_z = jf(build.machine_z_mm),
        prev1_w = profile.prev1_size[0],
        prev1_h = profile.prev1_size[1],
        prev2_w = profile.prev2_size[0],
        prev2_h = profile.prev2_size[1],
        raster_seg_cap = profile.raster_segments_capacity,
        max_file_version = profile.max_file_version,
        aa = timing.anti_alias_level,
        cprev_w = profile.cloud_prev_size[0],
        cprev_h = profile.cloud_prev_size[1],
        picture = profile.picture,
        max_accel_z = profile.machine_max_acceleration_z,
        resin_qualified_name = serde_json::to_string(&format!(
            "{}@{}@{}@{}",
            build.resin_brand_name,
            build.resin_resin_name,
            build.resin_film_name,
            build.resin_setting_name
        ))
        .unwrap_or_else(|_| "\"Generic@standard_resin@ACF@default\"".to_string()),
        resin_brand = serde_json::to_string(&build.resin_brand_name)
            .unwrap_or_else(|_| "\"Generic\"".to_string()),
        resin_resin = serde_json::to_string(&build.resin_resin_name)
            .unwrap_or_else(|_| "\"standard_resin\"".to_string()),
        resin_film =
            serde_json::to_string(&build.resin_film_name).unwrap_or_else(|_| "\"ACF\"".to_string()),
        resin_setting = serde_json::to_string(&build.resin_setting_name)
            .unwrap_or_else(|_| "\"default\"".to_string()),
        resin_price = jf(build.resin_price),
        resin_type = serde_json::to_string(&build.resin_type)
            .unwrap_or_else(|_| "\"Standard resin\"".to_string()),
        resin_volume = jf(build.resin_volume_ml),
        resin_density = jf(build.resin_density),
        target_temperature = jf(build.target_temperature),
        intelli_mode = if build.intelligent_release { 2 } else { 0 },
        transition_layers = timing.transition_layer_count,
        bottom_layers = timing.bottom_layer_count,
        bottom_exposure = jf(timing.bottom_exposure_sec),
        normal_exposure = jf(timing.normal_exposure_sec),
        wait_time = jf(timing.wait_time_before_cure_sec),
        layer_height = jf(timing.layer_height_mm),
        total_lift = jf(total_lift),
        lift_speed = jf(timing.lift_speed_mm_s),
        retract_speed = jf(timing.retract_speed_mm_s),
        multi_state = multi_state,
        multi_state_used = if timing.twostage { 1 } else { 0 },
        max_acceleration = profile.machine_max_acceleration_z,
    )
}

fn build_layers_controller_json(timing: &AfzTimingModel, layers: &[AfzPreparedLayer]) -> String {
    let mut entries = Vec::with_capacity(layers.len());
    let mut min_height: f32 = 0.0;

    let transition_start = timing.bottom_layer_count;
    let transition_end = transition_start + timing.transition_layer_count;

    for layer in layers {
        let layer_idx = layer.index as u32;

        let exposure = if layer_idx < transition_start {
            // Bottom layer
            timing.bottom_exposure_sec
        } else if layer_idx < transition_end && timing.transition_layer_count > 0 {
            // Transition layer — linear interpolation from bottom to normal exposure
            let progress =
                (layer_idx - transition_start) as f32 / timing.transition_layer_count as f32;
            timing.bottom_exposure_sec
                + (timing.normal_exposure_sec - timing.bottom_exposure_sec) * progress
        } else {
            timing.normal_exposure_sec
        };

        let is_bottom = layer_idx < transition_start;
        let lift_height = if is_bottom {
            timing.bottom_lift_height_mm
        } else {
            timing.lift_height_mm
        };
        let lift_speed = if is_bottom {
            timing.bottom_lift_speed_mm_s
        } else {
            timing.lift_speed_mm_s
        };

        entries.push(format!(
            r#"    {{
      "exposure_time": {exposure},
      "layer_index": {index},
      "layer_minheight": {min_h:.4},
      "layer_thickness": {thick},
      "zup_height": {lift_h},
      "zup_speed": {lift_s}
    }}"#,
            exposure = jf(exposure),
            index = layer.index,
            min_h = min_height,
            thick = jf(timing.layer_height_mm),
            lift_h = jf(lift_height),
            lift_s = jf(lift_speed),
        ));

        min_height += timing.layer_height_mm;
    }

    format!(
        r#"{{
  "count": {count},
  "paras": [
{entries}
  ]
}}"#,
        count = layers.len(),
        entries = entries.join(",\n"),
    )
}

fn build_print_info_json(
    job: &SliceJobV3,
    timing: &AfzTimingModel,
    build: &AfzBuildModel,
    layers: &[AfzPreparedLayer],
    layer_area_stats: &[LayerAreaStatsV3],
) -> String {
    // Pixel area in mm²
    let pixel_area_mm2 = (build.display_width_mm / job.source_width_px as f32)
        * (build.display_height_mm / job.source_height_px as f32);

    // Volume: sum of non-zero pixels × pixel area × layer height, converted mm³ → ml
    let total_volume_mm3: f32 = layers
        .iter()
        .map(|l| {
            layer_solid_pixel_count(layers, layer_area_stats, l.index) as f32
                * pixel_area_mm2
                * timing.layer_height_mm
        })
        .sum();
    let volume_ml = total_volume_mm3 / 1000.0;

    // Weight: volume × density
    let weight_g = volume_ml * build.resin_density;

    // Cost: (volume used / bottle volume) × bottle price
    let cost = if build.resin_volume_ml > 0.0 {
        (volume_ml / build.resin_volume_ml) * build.resin_price
    } else {
        0.0
    };

    // Print time estimate (seconds)
    let transition_start = timing.bottom_layer_count;
    let transition_end = transition_start + timing.transition_layer_count;

    let mut print_time_sec: f32 = 0.0;
    for layer in layers {
        let layer_idx = layer.index as u32;
        let is_bottom = layer_idx < transition_start;

        // Exposure
        let exposure = if layer_idx < transition_start {
            timing.bottom_exposure_sec
        } else if layer_idx < transition_end && timing.transition_layer_count > 0 {
            let progress =
                (layer_idx - transition_start) as f32 / timing.transition_layer_count as f32;
            timing.bottom_exposure_sec
                + (timing.normal_exposure_sec - timing.bottom_exposure_sec) * progress
        } else {
            timing.normal_exposure_sec
        };
        print_time_sec += exposure;

        // Wait time before cure
        print_time_sec += timing.wait_time_before_cure_sec;

        // Lift motion: stage 1 + stage 2 (time = distance / speed)
        let (lift_h1, lift_s1, lift_h2, lift_s2) = if is_bottom {
            (
                timing.bottom_lift_height_mm,
                timing.bottom_lift_speed_mm_s,
                timing.bottom_lift_height2_mm,
                timing.bottom_lift_speed2_mm_s,
            )
        } else {
            (
                timing.lift_height_mm,
                timing.lift_speed_mm_s,
                timing.lift_height2_mm,
                timing.lift_speed2_mm_s,
            )
        };

        if lift_s1 > 0.0 {
            print_time_sec += lift_h1 / lift_s1;
        }
        if lift_s2 > 0.0 {
            print_time_sec += lift_h2 / lift_s2;
        }

        // Retract motion: total retract distance = total lift distance
        let total_lift = lift_h1 + lift_h2;
        let (ret_s1, ret_s2) = if is_bottom {
            (
                timing.bottom_retract_speed_mm_s,
                timing.bottom_retract_speed2_mm_s,
            )
        } else {
            (timing.retract_speed_mm_s, timing.retract_speed2_mm_s)
        };

        // Retract uses total lift distance, split proportionally if two stages
        if ret_s1 > 0.0 && ret_s2 > 0.0 {
            // Approximate: split retract distance same as lift distance ratio
            let ret_h1 = lift_h1;
            let ret_h2 = total_lift - ret_h1;
            print_time_sec += ret_h1 / ret_s1;
            if ret_h2 > 0.0 {
                print_time_sec += ret_h2 / ret_s2;
            }
        } else if ret_s1 > 0.0 {
            print_time_sec += total_lift / ret_s1;
        }
    }

    format!(
        r#"{{
  "cost": {cost},
  "currency": "$",
  "print_time": {print_time},
  "volume": {volume},
  "weight": {weight}
}}"#,
        cost = jf(cost),
        print_time = jf(print_time_sec),
        volume = jf(volume_ml),
        weight = jf(weight_g),
    )
}

fn build_software_info_json() -> String {
    r#"{
  "mark": "ANYCUBIC-PC",
  "opengl": "3.3-CoreProfile",
  "os": "win-x64multi_machines_scene",
  "version": "4.0.02025-11-28 11:12:09"
}"#
    .to_string()
}

fn build_lcd_function_json() -> String {
    r#"{
  "models_processed_info": {
    "models": [],
    "scene_models_from": 0,
    "slice_paras_process": 1,
    "software_version": "AnycubicPhotonWorkshop_V4.0.0_20251226173139"
  },
  "rerf_function": {
    "enable": false,
    "model_name": "",
    "model_type": 1,
    "partition_exposure_array": [],
    "partition_num": 0
  }
}"#
    .to_string()
}

// ═══════════════════════════════════════════════════════════════════
//  Scene binary builder
// ═══════════════════════════════════════════════════════════════════

fn write_f32_le(out: &mut Vec<u8>, v: f32) {
    out.extend_from_slice(&v.to_le_bytes());
}

fn write_u32_le(out: &mut Vec<u8>, v: u32) {
    out.extend_from_slice(&v.to_le_bytes());
}

fn build_scene_binary(
    job: &SliceJobV3,
    timing: &AfzTimingModel,
    build: &AfzBuildModel,
    layers: &[AfzPreparedLayer],
    layer_area_stats: &[LayerAreaStatsV3],
) -> Vec<u8> {
    let layer_count = layers.len() as u32;
    let print_height = timing.layer_height_mm * layer_count as f32;

    let mut out = Vec::with_capacity(512 + layers.len() * 72);

    // Magic (16 bytes, null-padded)
    out.extend_from_slice(SCENE_MAGIC);

    // Software name (64 bytes, null-padded)
    let sw = b"DragonFruit";
    let mut sw_buf = [0u8; SCENE_SOFTWARE_LEN];
    let copy_len = sw.len().min(SCENE_SOFTWARE_LEN - 1);
    sw_buf[..copy_len].copy_from_slice(&sw[..copy_len]);
    out.extend_from_slice(&sw_buf);

    write_u32_le(&mut out, 3); // BinaryType: FPGA Release
    write_u32_le(&mut out, 2); // Version
    write_u32_le(&mut out, 0); // SliceType
    write_u32_le(&mut out, 0); // ModelUnit (mm)
    write_f32_le(&mut out, 1.0); // PointRatio
    write_u32_le(&mut out, layer_count);

    // Bounding rectangle as offsets from display centre
    // Use full display as conservative default
    let half_w = build.display_width_mm / 2.0;
    let half_h = build.display_height_mm / 2.0;
    write_f32_le(&mut out, -half_w); // XStart
    write_f32_le(&mut out, -half_h); // YStart
    write_f32_le(&mut out, 0.0); // ZMin
    write_f32_le(&mut out, half_w); // XEnd
    write_f32_le(&mut out, half_h); // YEnd
    write_f32_le(&mut out, print_height); // ZMax

    write_u32_le(&mut out, 0); // ModelStats

    // Padding (64 u32s)
    for _ in 0..SCENE_PADDING_U32S {
        write_u32_le(&mut out, 0);
    }

    // Separator "<---" (4 bytes)
    out.extend_from_slice(b"<---");

    // LayerDefCount
    write_u32_le(&mut out, layer_count);

    // Per-layer SceneLayerDef
    let mut pos_z: f32 = 0.0;
    for layer in layers {
        pos_z += timing.layer_height_mm;
        let solid_pixels = layer_solid_pixel_count(layers, layer_area_stats, layer.index);

        write_f32_le(&mut out, pos_z); // Height (absolute Z)

        // Area — we don't have contour data, so estimate from non-zero pixel count
        let pixel_area_mm2 = (build.display_width_mm / job.source_width_px as f32)
            * (build.display_height_mm / job.source_height_px as f32);
        let area = solid_pixels as f32 * pixel_area_mm2;
        write_f32_le(&mut out, area);

        // Bounding rect offsets from centre (conservative: full display)
        write_f32_le(&mut out, -half_w);
        write_f32_le(&mut out, -half_h);
        write_f32_le(&mut out, half_w);
        write_f32_le(&mut out, half_h);

        // ObjectCount — we don't track contours, default to 1 if layer has content
        let object_count = if solid_pixels > 0 { 1u32 } else { 0 };
        write_u32_le(&mut out, object_count);

        // MaxContourArea — same as total area as approximation
        write_f32_le(&mut out, area);

        // Padding (8 u32s)
        for _ in 0..SCENE_LAYER_DEF_PADDING_U32S {
            write_u32_le(&mut out, 0);
        }
    }

    // End marker "--->" (4 bytes)
    out.extend_from_slice(b"--->");

    out
}

fn layer_solid_pixel_count(
    layers: &[AfzPreparedLayer],
    layer_area_stats: &[LayerAreaStatsV3],
    layer_index: usize,
) -> u32 {
    layer_area_stats
        .get(layer_index)
        .map(|stats| stats.total_solid_pixels)
        .or_else(|| {
            layers
                .iter()
                .find(|layer| layer.index == layer_index)
                .map(|layer| layer.non_zero_pixel_count)
        })
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::SliceJobV3;

    fn make_test_job() -> SliceJobV3 {
        SliceJobV3 {
            output_format: ".azf".to_string(),
            source_width_px: 4,
            source_height_px: 4,
            width_px: 4,
            height_px: 4,
            build_width_mm: 10.0,
            build_depth_mm: 20.0,
            layer_height_mm: 0.05,
            total_layers: 2,
            anti_aliasing_level: "Off".to_string(),
            triangles_xyz: vec![],
            metadata_json: "{}".to_string(),
            x_packing_mode: "none".to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn scene_binary_has_correct_magic_and_markers() {
        let job = make_test_job();
        let timing = super::super::afz_metadata::parse_afz_timing_model(&job);
        let build = super::super::afz_metadata::parse_afz_build_model(&job);
        let layers = vec![AfzPreparedLayer {
            index: 0,
            encoded: vec![0x00, 16],
            non_zero_pixel_count: 0,
        }];

        let scene = build_scene_binary(&job, &timing, &build, &layers, &[]);

        // Check magic
        assert_eq!(&scene[0..14], b"ANYCUBIC-PWSZ\0");

        // Find separator and end marker
        let sep_pos = scene
            .windows(4)
            .position(|w| w == b"<---")
            .expect("separator should exist");
        let end_pos = scene
            .windows(4)
            .position(|w| w == b"--->")
            .expect("end marker should exist");
        assert!(end_pos > sep_pos);
    }

    #[test]
    fn afz_container_produces_valid_zip() {
        let job = make_test_job();
        let timing = super::super::afz_metadata::parse_afz_timing_model(&job);
        let build = super::super::afz_metadata::parse_afz_build_model(&job);
        let layers = vec![
            AfzPreparedLayer {
                index: 0,
                encoded: vec![0x00, 16],
                non_zero_pixel_count: 0,
            },
            AfzPreparedLayer {
                index: 1,
                encoded: vec![0xF0, 8, 0x00, 8],
                non_zero_pixel_count: 8,
            },
        ];

        let profile = super::super::afz_metadata::machine_profile_for_suffix(&build.key_suffix);
        let bytes = build_afz_container(&job, &timing, &build, profile, &layers, &[], None)
            .expect("should build");

        // Verify it's a valid ZIP
        let cursor = Cursor::new(&bytes);
        let mut archive = zip::ZipArchive::new(cursor).expect("should be valid ZIP");

        let expected_files = [
            SETTINGS_FILE,
            LAYERS_FILE,
            PRINT_INFO_FILE,
            SOFTWARE_INFO_FILE,
            SCENE_FILE,
            "layer_images/layer_0.pw0Img",
            "layer_images/layer_1.pw0Img",
        ];

        for name in &expected_files {
            assert!(
                archive.by_name(name).is_ok(),
                "missing expected file: {name}"
            );
        }
    }
}
