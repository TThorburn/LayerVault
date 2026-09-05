//! Anycubic plugin encoder implementations.
//!
//! Provides two encoders:
//! - `AffPluginEncoder` — Anycubic File Format (.aff), used by Photon and Photon Mono series
//! - `AzfPluginEncoder` — Anycubic Zip Format (.azf), used by Photon Mono M7 series and Mono 4 Ultra

mod aff_codec;
mod aff_layout;
mod aff_metadata;
mod aff_preview;
mod afz_layout;
mod afz_metadata;
mod afz_preview;
mod anycubic_preview_common;
mod anycubic_pw0;

use crate::encoders::{FormatEncoder, RawMaskStreamEncoder, RleStreamEncoder};
use crate::engine::SlicerV3Error;
use crate::types::{LayerAreaStatsV3, RenderedLayersV3, SliceJobV3};

use afz_layout::{build_afz_container, AfzPreparedLayer};
use afz_metadata::{machine_profile_for_suffix, parse_afz_build_model, parse_afz_timing_model};

use crossbeam_channel::bounded;
use std::path::Path;
use std::sync::mpsc;
use std::sync::Arc;
use std::thread;

pub struct AffPluginEncoder;
pub struct AzfPluginEncoder;

pub fn create_plugin_encoder() -> Vec<Box<dyn FormatEncoder>> {
    vec![
        Box::new(AffPluginEncoder),
        Box::new(AzfPluginEncoder),
    ]
}

// ═══════════════════════════════════════════════════════════════════
//  AFF FormatEncoder trait impl
// ═══════════════════════════════════════════════════════════════════

impl FormatEncoder for AffPluginEncoder {
    fn output_format(&self) -> &'static str {
        ".aff"
    }

    fn requires_raw_mask_layers(&self) -> bool {
        // Both streaming paths can produce the data they need; the engine
        // calls create_rle_stream_encoder first.
        true
    }

    fn requires_png_layers(&self) -> bool {
        false
    }

    fn requires_area_stats(&self) -> bool {
        true // needed for NonZeroPixelCount + volume calculation
    }

    fn create_rle_stream_encoder(
        &self,
        job: &SliceJobV3,
    ) -> Result<Option<Box<dyn RleStreamEncoder>>, SlicerV3Error> {
        let build = parse_aff_build_model(job);
        if aff_rle_format_for_suffix(&build.key_suffix) != AffRleFormat::Pw0 {
            return Ok(None); // .pws goes through raw-mask path
        }
        let total_pixels =
            (job.source_width_px as usize).saturating_mul(job.source_height_px as usize);
        Ok(Some(Box::new(AffRleStreamEncoder {
            job: job.clone(),
            total_pixels,
            prepared: Vec::with_capacity(job.total_layers as usize),
        })))
    }

    fn create_raw_mask_stream_encoder(
        &self,
        job: &SliceJobV3,
    ) -> Result<Option<Box<dyn RawMaskStreamEncoder>>, SlicerV3Error> {
        let build = parse_aff_build_model(job);
        if aff_rle_format_for_suffix(&build.key_suffix) != AffRleFormat::Pws {
            return Ok(None); // PW0 extensions go through RLE path
        }

        let timing = parse_aff_timing_model(job);
        let aa_level = timing.anti_alias_level as u8;
        let expected_pixels =
            (job.source_width_px as usize).saturating_mul(job.source_height_px as usize);

        let worker_count =
            cap_afz_workers_for_mask_bytes(choose_afz_encode_threads(), expected_pixels);
        let queue_depth = choose_afz_queue_depth(worker_count, expected_pixels);
        let (work_tx, work_rx) = bounded::<(u32, Vec<u8>)>(queue_depth);
        let (result_tx, result_rx) = mpsc::channel::<Result<AffPreparedLayer, SlicerV3Error>>();
        let mut workers = Vec::with_capacity(worker_count);

        for _ in 0..worker_count {
            let work_rx = work_rx.clone();
            let result_tx = result_tx.clone();
            let pixels = expected_pixels;
            let handle = thread::spawn(move || loop {
                let Ok((layer_index, raw_mask)) = work_rx.recv() else { break; };

                if raw_mask.is_empty() {
                    let prep = encode_single_aff_pws_empty_layer(layer_index as usize, pixels, aa_level);
                    crate::pipeline::return_mask_to_pool(raw_mask);
                    if result_tx.send(Ok(prep)).is_err() { break; }
                    continue;
                }
                if raw_mask.len() != pixels {
                    let len = raw_mask.len();
                    crate::pipeline::return_mask_to_pool(raw_mask);
                    let _ = result_tx.send(Err(SlicerV3Error::MissingRenderedLayerPayload(
                        format!("AFF layer {layer_index} size mismatch: expected {pixels}, got {len}"),
                    )));
                    continue;
                }
                let prep = encode_single_aff_pws_layer(layer_index as usize, &raw_mask, aa_level);
                crate::pipeline::return_mask_to_pool(raw_mask);
                if result_tx.send(Ok(prep)).is_err() { break; }
            });
            workers.push(handle);
        }
        drop(work_rx);
        drop(result_tx);

        Ok(Some(Box::new(AffRawMaskStreamEncoder {
            job: job.clone(),
            work_tx: Some(work_tx),
            result_rx,
            workers,
            consumed_layers: 0,
        })))
    }

    fn encode_container_from_rendered_layers(
        &self,
        job: &SliceJobV3,
        rendered_layers: &RenderedLayersV3,
        layer_area_stats: &[LayerAreaStatsV3],
    ) -> Result<Vec<u8>, SlicerV3Error> {
        self.encode_container_from_rendered_layers_with_progress(
            job, rendered_layers, layer_area_stats, None,
        )
    }

    fn estimate_encode_progress_units(&self, rendered_layers: &RenderedLayersV3) -> u32 {
        rendered_layers.raw_mask_layers.as_ref().map(|l| l.len() as u32).unwrap_or(0).saturating_mul(2)
    }

    fn encode_container_from_rendered_layers_with_progress(
        &self,
        job: &SliceJobV3,
        rendered_layers: &RenderedLayersV3,
        _layer_area_stats: &[LayerAreaStatsV3],
        on_progress: Option<&dyn Fn(u32, u32)>,
    ) -> Result<Vec<u8>, SlicerV3Error> {
        let report = |done, total| {
            if let Some(cb) = on_progress {
                cb(done, total);
            }
        };

        let Some(raw_masks) = rendered_layers.raw_mask_layers.as_ref() else {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "raw mask layers are required for AFF encoding".to_string(),
            ));
        };
        if raw_masks.is_empty() {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "no rendered layers were provided for AFF encoding".to_string(),
            ));
        }

        let expected_pixels =
            (job.source_width_px as usize).saturating_mul(job.source_height_px as usize);
        let timing = parse_aff_timing_model(job);
        let build = parse_aff_build_model(job);
        let profile = aff_machine_profile_for_suffix(&build.key_suffix);

        let total_layers = raw_masks.len();
        let mut prepared = Vec::with_capacity(total_layers);
        let total_units = job.total_layers.saturating_mul(2);

        for (i, mask) in raw_masks.iter().enumerate() {
            if mask.len() != expected_pixels {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFF layer {i} size mismatch: expected {expected_pixels} bytes, got {}",
                    mask.len()
                )));
            }
            let non_zero = mask.iter().filter(|&&b| b > 0).count() as u32;
            let encoded = if aff_rle_format_for_suffix(&build.key_suffix) == AffRleFormat::Pws {
                encode_pws(mask, timing.anti_alias_level as u8)
            } else {
                anycubic_pw0::encode_pw0(mask)
            };
            if encoded.is_empty() && non_zero > 0 {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFF layer {i} encoded to zero bytes (non_zero_pixels={non_zero})"
                )));
            }
            prepared.push(AffPreparedLayer {
                index: i,
                encoded,
                non_zero_pixel_count: non_zero,
            });
            report((i as u32).saturating_mul(2).saturating_add(1), total_units);
        }

        let result = build_aff_container(job, &timing, &build, profile, &prepared)?;
        report(total_units, total_units);
        Ok(result)
    }
}

// ═══════════════════════════════════════════════════════════════════
//  AZF threading helpers
// ═══════════════════════════════════════════════════════════════════

fn choose_afz_encode_threads() -> usize {
    let hw = thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    let env = std::env::var("DF_V3_AFZ_ENCODE_THREADS")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|v| *v >= 1)
        .unwrap_or(hw);
    env.clamp(1, hw)
}

fn cap_afz_workers_for_mask_bytes(requested: usize, bytes_per_mask: usize) -> usize {
    // Allow operator override for memory budget (DF_V3_AFZ_INFLIGHT_MB / DF_V3_AFF_INFLIGHT_MB).
    let env_mb = std::env::var("DF_V3_AFZ_INFLIGHT_MB")
        .ok()
        .or_else(|| std::env::var("DF_V3_AFF_INFLIGHT_MB").ok())
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|v| *v > 0);

    if let Some(max_mb) = env_mb {
        let max_bytes = max_mb.saturating_mul(1024 * 1024);
        let max_workers = if bytes_per_mask > 0 {
            (max_bytes / bytes_per_mask).clamp(1, requested)
        } else {
            requested
        };
        return max_workers.max(1);
    }

    let mut capped = requested.max(1);

    if bytes_per_mask >= 48 * 1024 * 1024 {
        capped = capped.min(2);
    } else if bytes_per_mask >= 24 * 1024 * 1024 {
        capped = capped.min(4);
    } else if bytes_per_mask >= 12 * 1024 * 1024 {
        capped = capped.min(8);
    }

    capped.max(1)
}

fn choose_afz_queue_depth(worker_count: usize, bytes_per_mask: usize) -> usize {
    if bytes_per_mask >= 48 * 1024 * 1024 {
        1
    } else if bytes_per_mask >= 24 * 1024 * 1024 {
        2
    } else if bytes_per_mask >= 12 * 1024 * 1024 {
        3
    } else {
        (worker_count.saturating_mul(3)).clamp(3, 24)
    }
}

/// PW0-encode a single raw mask layer.
fn encode_single_afz_layer(index: usize, raw_mask: &[u8]) -> AfzPreparedLayer {
    let non_zero = raw_mask.iter().filter(|&&b| b > 0).count() as u32;
    let encoded = anycubic_pw0::encode_pw0(raw_mask);
    AfzPreparedLayer {
        index,
        encoded,
        non_zero_pixel_count: non_zero,
    }
}

/// PW0-encode an all-black empty layer without materializing a full-size zero mask.
/// Used when the streaming pipeline sends a 0-byte sentinel for layers with no geometry.
fn encode_single_afz_empty_layer(index: usize, pixel_count: usize) -> AfzPreparedLayer {
    let encoded = anycubic_pw0::encode_pw0(&vec![0u8; pixel_count]);
    AfzPreparedLayer {
        index,
        encoded,
        non_zero_pixel_count: 0,
    }
}

/// PW0-encode a single rasterized RLE layer without expanding to a raw mask.
fn encode_single_afz_rle_layer(
    index: usize,
    runs: &[crate::rle::RleRun],
    pixel_count: usize,
) -> AfzPreparedLayer {
    let encoded = anycubic_pw0::encode_pw0_from_rle(runs, pixel_count);
    AfzPreparedLayer {
        index,
        encoded,
        non_zero_pixel_count: 0,
    }
}

// ═══════════════════════════════════════════════════════════════════
//  AZF streaming encoder (multi-threaded)
// ═══════════════════════════════════════════════════════════════════

struct AzfStreamEncoder {
    job: SliceJobV3,
    work_tx: Option<crossbeam_channel::Sender<(u32, Vec<u8>)>>,
    result_rx: mpsc::Receiver<Result<AfzPreparedLayer, SlicerV3Error>>,
    workers: Vec<thread::JoinHandle<()>>,
    consumed_layers: u32,
}

struct AzfRleStreamEncoder {
    job: SliceJobV3,
    total_pixels: usize,
    prepared: Vec<AfzPreparedLayer>,
    area_stats: Vec<LayerAreaStatsV3>,
}

impl RawMaskStreamEncoder for AzfStreamEncoder {
    fn consume_raw_mask_layer(
        &mut self,
        layer_index: u32,
        raw_mask: Vec<u8>,
    ) -> Result<(), SlicerV3Error> {
        let Some(ref tx) = self.work_tx else {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "AFZ streaming encoder no longer accepts layers after finalize".to_string(),
            ));
        };

        tx.send((layer_index, raw_mask)).map_err(|_| {
            SlicerV3Error::MissingRenderedLayerPayload(
                "AFZ streaming worker channel closed unexpectedly".to_string(),
            )
        })?;
        self.consumed_layers = self.consumed_layers.saturating_add(1);
        Ok(())
    }

    fn finalize_to_bytes(mut self: Box<Self>) -> Result<Vec<u8>, SlicerV3Error> {
        if self.consumed_layers == 0 {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "no rendered layers were provided for AFZ encoding".to_string(),
            ));
        }

        // Close producer channel and let workers drain.
        let _ = self.work_tx.take();

        while let Some(handle) = self.workers.pop() {
            if handle.join().is_err() {
                return Err(SlicerV3Error::UnsupportedOutput(
                    "AFZ streaming worker panicked".to_string(),
                ));
            }
        }

        // Collect results in layer order.
        let expected = self.consumed_layers as usize;
        let mut ordered: Vec<Option<AfzPreparedLayer>> = Vec::with_capacity(expected);
        ordered.resize_with(expected, || None);

        for _ in 0..expected {
            let msg = self.result_rx.recv().map_err(|_| {
                SlicerV3Error::MissingRenderedLayerPayload(
                    "AFZ streaming worker results ended unexpectedly".to_string(),
                )
            })?;

            let prepared = msg?;
            let index = prepared.index;
            if index >= expected {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFZ worker emitted out-of-range layer index {} (expected < {})",
                    index, expected
                )));
            }
            if ordered[index].is_some() {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFZ worker emitted duplicate layer index {}",
                    index
                )));
            }
            ordered[index] = Some(prepared);
        }

        let mut prepared = Vec::with_capacity(expected);
        for (i, slot) in ordered.into_iter().enumerate() {
            let Some(layer) = slot else {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFZ layer {} missing from streaming worker output",
                    i
                )));
            };
            prepared.push(layer);
        }

        let timing = parse_afz_timing_model(&self.job);
        let build = parse_afz_build_model(&self.job);
        let profile = machine_profile_for_suffix(&build.key_suffix);

        let fallback_stats = prepared
            .iter()
            .map(|layer| LayerAreaStatsV3 {
                total_solid_pixels: layer.non_zero_pixel_count,
                ..LayerAreaStatsV3::default()
            })
            .collect::<Vec<_>>();

        build_afz_container(
            &self.job,
            &timing,
            &build,
            profile,
            &prepared,
            &fallback_stats,
            None,
        )
    }

    fn finalize_to_path(self: Box<Self>, output_path: &Path) -> Result<(), SlicerV3Error> {
        let bytes = self.finalize_to_bytes()?;
        std::fs::write(output_path, bytes)?;
        Ok(())
    }
}

impl RleStreamEncoder for AzfRleStreamEncoder {
    fn consume_rle_layer(
        &mut self,
        layer_index: u32,
        runs: Vec<crate::rle::RleRun>,
    ) -> Result<(), SlicerV3Error> {
        self.prepared.push(encode_single_afz_rle_layer(
            layer_index as usize,
            &runs,
            self.total_pixels,
        ));
        Ok(())
    }

    fn set_area_stats(&mut self, stats: Vec<LayerAreaStatsV3>) {
        self.area_stats = stats;
    }

    fn parallel_encode_fn(
        &self,
    ) -> Option<
        Arc<dyn Fn(u32, &[crate::rle::RleRun]) -> Result<Vec<u8>, SlicerV3Error> + Send + Sync>,
    > {
        let total_pixels = self.total_pixels;
        Some(Arc::new(
            move |_layer_index: u32, runs: &[crate::rle::RleRun]| {
                Ok(anycubic_pw0::encode_pw0_from_rle(runs, total_pixels))
            },
        ))
    }

    fn store_encoded_layer(&mut self, layer_index: u32, bytes: Vec<u8>) {
        self.prepared.push(AfzPreparedLayer {
            index: layer_index as usize,
            encoded: bytes,
            non_zero_pixel_count: 0,
        });
    }

    fn finalize_to_bytes(mut self: Box<Self>) -> Result<Vec<u8>, SlicerV3Error> {
        if self.prepared.is_empty() {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "no rendered layers were provided for AFZ RLE encoding".to_string(),
            ));
        }

        self.prepared.sort_unstable_by_key(|layer| layer.index);

        let timing = parse_afz_timing_model(&self.job);
        let build = parse_afz_build_model(&self.job);
        let profile = machine_profile_for_suffix(&build.key_suffix);

        build_afz_container(
            &self.job,
            &timing,
            &build,
            profile,
            &self.prepared,
            &self.area_stats,
            None,
        )
    }
}

// ═══════════════════════════════════════════════════════════════════
//  AZF FormatEncoder trait impl
// ═══════════════════════════════════════════════════════════════════

impl FormatEncoder for AzfPluginEncoder {
    fn output_format(&self) -> &'static str {
        ".azf"
    }

    fn requires_raw_mask_layers(&self) -> bool {
        true
    }

    fn requires_png_layers(&self) -> bool {
        false
    }

    fn create_raw_mask_stream_encoder(
        &self,
        job: &SliceJobV3,
    ) -> Result<Option<Box<dyn RawMaskStreamEncoder>>, SlicerV3Error> {
        let expected_pixels =
            (job.source_width_px as usize).saturating_mul(job.source_height_px as usize);

        let worker_count =
            cap_afz_workers_for_mask_bytes(choose_afz_encode_threads(), expected_pixels);
        let queue_depth = choose_afz_queue_depth(worker_count, expected_pixels);
        let (work_tx, work_rx) = bounded::<(u32, Vec<u8>)>(queue_depth);
        let (result_tx, result_rx) = mpsc::channel::<Result<AfzPreparedLayer, SlicerV3Error>>();
        let mut workers = Vec::with_capacity(worker_count);

        for _ in 0..worker_count {
            let work_rx = work_rx.clone();
            let result_tx = result_tx.clone();
            let worker_expected_pixels = expected_pixels;

            let handle = thread::spawn(move || loop {
                let Ok((layer_index, raw_mask)) = work_rx.recv() else {
                    break;
                };

                // Empty sentinel from pipeline = layer with no geometry (all black).
                if raw_mask.is_empty() {
                    let prepared = encode_single_afz_empty_layer(
                        layer_index as usize,
                        worker_expected_pixels,
                    );
                    crate::pipeline::return_mask_to_pool(raw_mask);
                    if result_tx.send(Ok(prepared)).is_err() {
                        break;
                    }
                    continue;
                }

                if raw_mask.len() != worker_expected_pixels {
                    let len = raw_mask.len();
                    crate::pipeline::return_mask_to_pool(raw_mask);
                    let _ = result_tx.send(Err(SlicerV3Error::MissingRenderedLayerPayload(
                        format!(
                            "AFZ layer {layer_index} size mismatch: expected {} bytes, got {}",
                            worker_expected_pixels, len
                        ),
                    )));
                    continue;
                }

                let prepared = encode_single_afz_layer(layer_index as usize, &raw_mask);
                crate::pipeline::return_mask_to_pool(raw_mask);

                if result_tx.send(Ok(prepared)).is_err() {
                    break;
                }
            });
            workers.push(handle);
        }

        // Drop extra clones so channels close properly when work_tx is dropped.
        drop(work_rx);
        drop(result_tx);

        Ok(Some(Box::new(AzfStreamEncoder {
            job: job.clone(),
            work_tx: Some(work_tx),
            result_rx,
            workers,
            consumed_layers: 0,
        })))
    }

    fn create_rle_stream_encoder(
        &self,
        job: &SliceJobV3,
    ) -> Result<Option<Box<dyn RleStreamEncoder>>, SlicerV3Error> {
        let total_pixels =
            (job.source_width_px as usize).saturating_mul(job.source_height_px as usize);
        Ok(Some(Box::new(AzfRleStreamEncoder {
            job: job.clone(),
            total_pixels,
            prepared: Vec::with_capacity(job.total_layers as usize),
            area_stats: vec![LayerAreaStatsV3::default(); job.total_layers as usize],
        })))
    }

    fn encode_container_from_rendered_layers(
        &self,
        job: &SliceJobV3,
        rendered_layers: &RenderedLayersV3,
        layer_area_stats: &[LayerAreaStatsV3],
    ) -> Result<Vec<u8>, SlicerV3Error> {
        let Some(raw_masks) = rendered_layers.raw_mask_layers.as_ref() else {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "raw mask layers are required for AFZ encoding".to_string(),
            ));
        };

        if raw_masks.is_empty() {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "no rendered layers were provided for AFZ encoding".to_string(),
            ));
        }

        let expected_pixels =
            (job.source_width_px as usize).saturating_mul(job.source_height_px as usize);
        for (idx, layer) in raw_masks.iter().enumerate() {
            if layer.len() != expected_pixels {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFZ layer {idx} size mismatch: expected {expected_pixels} bytes, got {}",
                    layer.len()
                )));
            }
        }

        let prepared: Vec<AfzPreparedLayer> = raw_masks
            .iter()
            .enumerate()
            .map(|(i, mask)| {
                let layer = encode_single_afz_layer(i, mask);
                if layer.encoded.is_empty() {
                    // non-fatal for empty layers but worth noting
                }
                layer
            })
            .collect();

        let timing = parse_afz_timing_model(job);
        let build = parse_afz_build_model(job);
        let profile = machine_profile_for_suffix(&build.key_suffix);

        build_afz_container(job, &timing, &build, profile, &prepared, layer_area_stats, None)
    }

    fn estimate_encode_progress_units(&self, rendered_layers: &RenderedLayersV3) -> u32 {
        rendered_layers.raw_mask_layers.as_ref().map(|l| l.len() as u32).unwrap_or(0).saturating_mul(2)
    }

    fn encode_container_from_rendered_layers_with_progress(
        &self,
        job: &SliceJobV3,
        rendered_layers: &RenderedLayersV3,
        layer_area_stats: &[LayerAreaStatsV3],
        on_progress: Option<&dyn Fn(u32, u32)>,
    ) -> Result<Vec<u8>, SlicerV3Error> {
        let report = |done, total| {
            if let Some(cb) = on_progress {
                cb(done, total);
            }
        };
        let Some(raw_masks) = rendered_layers.raw_mask_layers.as_ref() else {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "raw mask layers are required for AFZ encoding".to_string(),
            ));
        };
        if raw_masks.is_empty() {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "no rendered layers were provided for AFZ encoding".to_string(),
            ));
        }

        let expected_pixels =
            (job.source_width_px as usize).saturating_mul(job.source_height_px as usize);
        let total_layers = raw_masks.len();
        let total_units = job.total_layers.saturating_mul(2);
        let mut prepared = Vec::with_capacity(total_layers);

        for (i, mask) in raw_masks.iter().enumerate() {
            if mask.len() != expected_pixels {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFZ layer {i} size mismatch: expected {expected_pixels} bytes, got {}",
                    mask.len()
                )));
            }
            let layer = encode_single_afz_layer(i, mask);
            if layer.encoded.is_empty() && layer.non_zero_pixel_count > 0 {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(format!(
                    "AFZ layer {i} encoded to zero bytes with {nz} non-zero pixels",
                    nz = layer.non_zero_pixel_count
                )));
            }
            prepared.push(layer);
            report((i as u32).saturating_mul(2).saturating_add(1), total_units);
        }

        let timing = parse_afz_timing_model(job);
        let build = parse_afz_build_model(job);
        let profile = machine_profile_for_suffix(&build.key_suffix);

        let result = build_afz_container(job, &timing, &build, profile, &prepared, layer_area_stats, None)?;
        report(total_units, total_units);
        Ok(result)
    }

    fn encode_container_to_path(
        &self,
        job: &SliceJobV3,
        rendered_layers: &RenderedLayersV3,
        layer_area_stats: &[LayerAreaStatsV3],
        output_path: &Path,
    ) -> Result<(), SlicerV3Error> {
        let bytes =
            self.encode_container_from_rendered_layers(job, rendered_layers, layer_area_stats)?;
        std::fs::write(output_path, bytes)?;
        Ok(())
    }

    fn read_layer_preview_png(
        &self,
        path: &Path,
        layer_number: u32,
    ) -> Result<Vec<u8>, SlicerV3Error> {
        self::read_layer_preview_png(path, layer_number).map_err(SlicerV3Error::LayerPreview)
    }
}

// ═══════════════════════════════════════════════════════════════════
//  AFF (Anycubic File Format) encoders
// ═══════════════════════════════════════════════════════════════════

use aff_codec::{aff_rle_format_for_suffix, encode_pw0_from_rle, encode_pws, AffRleFormat};
use aff_layout::{build_aff_container, AffPreparedLayer};
use aff_metadata::{
    machine_profile_for_suffix as aff_machine_profile_for_suffix,
    parse_aff_build_model,
    parse_aff_timing_model,
};

struct AffRleStreamEncoder {
    job: SliceJobV3,
    total_pixels: usize,
    prepared: Vec<AffPreparedLayer>,
}

impl RleStreamEncoder for AffRleStreamEncoder {
    fn consume_rle_layer(
        &mut self,
        layer_index: u32,
        runs: Vec<crate::rle::RleRun>,
    ) -> Result<(), SlicerV3Error> {
        let encoded = encode_pw0_from_rle(&runs, self.total_pixels);
        self.prepared.push(AffPreparedLayer {
            index: layer_index as usize,
            encoded,
            non_zero_pixel_count: 0, // backfilled via set_area_stats
        });
        Ok(())
    }

    fn set_area_stats(&mut self, stats: Vec<LayerAreaStatsV3>) {
        for layer in &mut self.prepared {
            if let Some(s) = stats.get(layer.index) {
                layer.non_zero_pixel_count = s.total_solid_pixels;
            }
        }
    }

    fn parallel_encode_fn(
        &self,
    ) -> Option<Arc<dyn Fn(u32, &[crate::rle::RleRun]) -> Result<Vec<u8>, SlicerV3Error> + Send + Sync>> {
        let total_pixels = self.total_pixels;
        Some(Arc::new(move |_idx, runs| Ok(encode_pw0_from_rle(runs, total_pixels))))
    }

    fn store_encoded_layer(&mut self, layer_index: u32, bytes: Vec<u8>) {
        self.prepared.push(AffPreparedLayer {
            index: layer_index as usize,
            encoded: bytes,
            non_zero_pixel_count: 0,
        });
    }

    fn finalize_to_bytes(mut self: Box<Self>) -> Result<Vec<u8>, SlicerV3Error> {
        if self.prepared.is_empty() {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "no rendered layers were provided for AFF encoding".to_string(),
            ));
        }
        self.prepared.sort_unstable_by_key(|l| l.index);

        let timing = parse_aff_timing_model(&self.job);
        let build = parse_aff_build_model(&self.job);
        let profile = aff_machine_profile_for_suffix(&build.key_suffix);

        build_aff_container(&self.job, &timing, &build, profile, &self.prepared)
    }
}

struct AffRawMaskStreamEncoder {
    job: SliceJobV3,
    work_tx: Option<crossbeam_channel::Sender<(u32, Vec<u8>)>>,
    result_rx: mpsc::Receiver<Result<AffPreparedLayer, SlicerV3Error>>,
    workers: Vec<thread::JoinHandle<()>>,
    consumed_layers: u32,
}

impl RawMaskStreamEncoder for AffRawMaskStreamEncoder {
    fn consume_raw_mask_layer(
        &mut self,
        layer_index: u32,
        raw_mask: Vec<u8>,
    ) -> Result<(), SlicerV3Error> {
        let Some(ref tx) = self.work_tx else {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "AFF streaming encoder no longer accepts layers after finalize".to_string(),
            ));
        };
        tx.send((layer_index, raw_mask)).map_err(|_| {
            SlicerV3Error::MissingRenderedLayerPayload(
                "AFF streaming worker channel closed unexpectedly".to_string(),
            )
        })?;
        self.consumed_layers = self.consumed_layers.saturating_add(1);
        Ok(())
    }

    fn finalize_to_bytes(mut self: Box<Self>) -> Result<Vec<u8>, SlicerV3Error> {
        if self.consumed_layers == 0 {
            return Err(SlicerV3Error::MissingRenderedLayerPayload(
                "no rendered layers were provided for AFF encoding".to_string(),
            ));
        }
        let _ = self.work_tx.take();
        while let Some(handle) = self.workers.pop() {
            if handle.join().is_err() {
                return Err(SlicerV3Error::UnsupportedOutput(
                    "AFF streaming worker panicked".to_string(),
                ));
            }
        }

        let expected = self.consumed_layers as usize;
        let mut ordered: Vec<Option<AffPreparedLayer>> = Vec::with_capacity(expected);
        ordered.resize_with(expected, || None);
        for _ in 0..expected {
            let prepared = self.result_rx.recv().map_err(|_| {
                SlicerV3Error::MissingRenderedLayerPayload(
                    "AFF streaming worker results ended unexpectedly".to_string(),
                )
            })??;
            let idx = prepared.index;
            if idx >= expected {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(
                    format!("AFF worker emitted out-of-range layer index {}", idx),
                ));
            }
            ordered[idx] = Some(prepared);
        }

        let mut prepared = Vec::with_capacity(expected);
        for (i, slot) in ordered.into_iter().enumerate() {
            let Some(layer) = slot else {
                return Err(SlicerV3Error::MissingRenderedLayerPayload(
                    format!("AFF layer {} missing from streaming worker output", i),
                ));
            };
            prepared.push(layer);
        }

        let timing = parse_aff_timing_model(&self.job);
        let build = parse_aff_build_model(&self.job);
        let profile = aff_machine_profile_for_suffix(&build.key_suffix);
        build_aff_container(&self.job, &timing, &build, profile, &prepared)
    }
}

fn encode_single_aff_pws_layer(index: usize, raw_mask: &[u8], aa_level: u8) -> AffPreparedLayer {
    let non_zero = raw_mask.iter().filter(|&&b| b > 0).count() as u32;
    let encoded = encode_pws(raw_mask, aa_level);
    AffPreparedLayer { index, encoded, non_zero_pixel_count: non_zero }
}

fn encode_single_aff_pws_empty_layer(index: usize, pixel_count: usize, aa_level: u8) -> AffPreparedLayer {
    let encoded = encode_pws(&vec![0u8; pixel_count], aa_level);
    AffPreparedLayer { index, encoded, non_zero_pixel_count: 0 }
}

/// Reads a single layer preview PNG from an AFZ (Anycubic Zip Format) file.
/// `layer_number` is 1-based.
pub fn read_layer_preview_png(path: &Path, layer_number: u32) -> Result<Vec<u8>, String> {
    use std::io::Read;

    if layer_number == 0 {
        return Err("Layer number must be >= 1".to_string());
    }

    let file = std::fs::File::open(path).map_err(|e| format!("Failed opening AFZ file: {e}"))?;
    let mut zip =
        zip::ZipArchive::new(file).map_err(|e| format!("Failed reading AFZ zip: {e}"))?;

    // Read settings JSON for canvas dimensions.
    let (width_px, height_px) = {
        let mut entry = zip
            .by_name("anycubic_photon_resins.pwsp")
            .map_err(|e| format!("AFZ settings file missing: {e}"))?;
        let mut json_str = String::new();
        entry
            .read_to_string(&mut json_str)
            .map_err(|e| format!("AFZ settings read failed: {e}"))?;
        let value: serde_json::Value = serde_json::from_str(&json_str)
            .map_err(|e| format!("AFZ settings JSON parse failed: {e}"))?;
        let machine = value
            .get("machine_type")
            .ok_or_else(|| "AFZ settings missing machine_type".to_string())?;
        let w = machine
            .get("res_x")
            .and_then(|v| v.as_u64())
            .ok_or_else(|| "AFZ settings missing machine_type.res_x".to_string())?
            as u32;
        let h = machine
            .get("res_y")
            .and_then(|v| v.as_u64())
            .ok_or_else(|| "AFZ settings missing machine_type.res_y".to_string())?
            as u32;
        (w, h)
    };

    if width_px == 0 || height_px == 0 {
        return Err(format!(
            "AFZ file reports invalid dimensions {width_px}×{height_px}"
        ));
    }

    let layer_index = layer_number - 1;
    let layer_name = format!("layer_images/layer_{}.pw0Img", layer_index);

    let mut rle_bytes = Vec::new();
    {
        let mut entry = zip.by_name(&layer_name).map_err(|e| {
            format!("AFZ layer {layer_number} not found ({layer_name}): {e}")
        })?;
        rle_bytes.reserve(entry.size() as usize);
        entry
            .read_to_end(&mut rle_bytes)
            .map_err(|e| format!("AFZ layer {layer_number} read failed: {e}"))?;
    }

    let expected_pixels = width_px as usize * height_px as usize;
    let pixels = anycubic_pw0::decode_pw0(&rle_bytes, expected_pixels);
    encode_pixels_as_grayscale_png(width_px, height_px, &pixels)
}

/// Encodes a flat 8-bit grayscale pixel buffer as a PNG.
fn encode_pixels_as_grayscale_png(
    width: u32,
    height: u32,
    pixels: &[u8],
) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    let mut encoder = png::Encoder::new(&mut out, width, height);
    encoder.set_color(png::ColorType::Grayscale);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder
        .write_header()
        .map_err(|e| format!("AFZ PNG header write failed: {e}"))?;
    writer
        .write_image_data(pixels)
        .map_err(|e| format!("AFZ PNG data write failed: {e}"))?;
    drop(writer);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_job(output_format: &str, layers: u32) -> SliceJobV3 {
        SliceJobV3 {
            output_format: output_format.to_string(),
            format_version: None,
            source_width_px: 16,
            source_height_px: 16,
            width_px: 16,
            height_px: 16,
            build_width_mm: 10.0,
            build_depth_mm: 10.0,
            layer_height_mm: 0.05,
            total_layers: layers,
            export_thumbnail_png_base64: None,
            png_compression_strategy: "balanced".to_string(),
            container_compression_level: 2,
            anti_aliasing_level: "Off".to_string(),
            aa_on_supports: false,
            minimum_aa_alpha_percent: 35.0,
            mirror_x: false,
            mirror_y: false,
            triangles_xyz: vec![],
            metadata_json: "{}".to_string(),
            x_packing_mode: "none".to_string(),
            ..Default::default()
        }
    }

    fn make_rendered_layers(count: usize, pixels: usize) -> RenderedLayersV3 {
        let mask = vec![128u8; pixels];
        RenderedLayersV3 {
            raw_mask_layers: Some(vec![mask; count]),
            ..Default::default()
        }
    }

    #[test]
    fn aff_encoder_output_format() {
        assert_eq!(AffPluginEncoder.output_format(), ".aff");
    }

    #[test]
    fn azf_encoder_output_format() {
        assert_eq!(AzfPluginEncoder.output_format(), ".azf");
    }

    #[test]
    fn aff_encoder_requires_raw_mask_not_png() {
        assert!(AffPluginEncoder.requires_raw_mask_layers());
        assert!(!AffPluginEncoder.requires_png_layers());
    }

    #[test]
    fn azf_encoder_requires_raw_mask_not_png() {
        assert!(AzfPluginEncoder.requires_raw_mask_layers());
        assert!(!AzfPluginEncoder.requires_png_layers());
    }

    #[test]
    fn estimate_progress_units_returns_layers_times_two() {
        let rendered = make_rendered_layers(10, 256);
        assert_eq!(AffPluginEncoder.estimate_encode_progress_units(&rendered), 20);
        assert_eq!(AzfPluginEncoder.estimate_encode_progress_units(&rendered), 20);
    }

    #[test]
    fn estimate_progress_units_zero_for_empty_layers() {
        let rendered = RenderedLayersV3 {
            raw_mask_layers: None,
            ..Default::default()
        };
        assert_eq!(AffPluginEncoder.estimate_encode_progress_units(&rendered), 0);
        assert_eq!(AzfPluginEncoder.estimate_encode_progress_units(&rendered), 0);
    }

    #[test]
    fn aff_rle_encoder_declines_pws_suffix() {
        let job = make_job(".aff", 1);
        // Default suffix "pwmo" → PW0 → RLE encoder accepted
        let rle = AffPluginEncoder.create_rle_stream_encoder(&job).unwrap();
        assert!(rle.is_some());
    }

    #[test]
    fn azf_creates_both_streaming_encoders() {
        let job = make_job(".azf", 1);
        let rle = AzfPluginEncoder.create_rle_stream_encoder(&job).unwrap();
        let raw = AzfPluginEncoder.create_raw_mask_stream_encoder(&job).unwrap();
        assert!(rle.is_some());
        assert!(raw.is_some());
    }

    #[test]
    fn encode_empty_layers_rejected() {
        let job = make_job(".aff", 1);
        let empty = RenderedLayersV3::default();
        let stats = vec![];
        let err = AffPluginEncoder
            .encode_container_from_rendered_layers(&job, &empty, &stats)
            .unwrap_err();
        let msg = format!("{err:?}").to_lowercase();
        assert!(msg.contains("raw mask layers") || msg.contains("no rendered layers"),
            "unexpected error: {msg}");
    }
}
