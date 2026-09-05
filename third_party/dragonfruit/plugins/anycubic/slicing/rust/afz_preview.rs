//! Thumbnail handling for AFZ files.
//!
//! AFZ stores preview images as standard PNGs inside the ZIP archive,
//! so we just need to decode the base64 thumbnail from the job, resize
//! it to the required dimensions, and re-encode as PNG.
//!
//! When no thumbnail PNG is provided by the job, a dithered diagonal gradient
//! (dark purple → dark green, matching CTB/Elegoo) is generated as a fallback.

use super::anycubic_preview_common::{decode_base64, decode_png_rgb8, gradient_preview_rgb, resize_rgb_nearest};
use crate::engine::SlicerV3Error;

/// Encode RGB8 pixels into a PNG byte vector.
fn encode_png_rgb8(width: u32, height: u32, rgb: &[u8]) -> Result<Vec<u8>, SlicerV3Error> {
    let mut buf = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut buf, width, height);
        encoder.set_color(png::ColorType::Rgb);
        encoder.set_depth(png::BitDepth::Eight);
        encoder.set_compression(png::Compression::Fast);

        let mut writer = encoder
            .write_header()
            .map_err(|e| SlicerV3Error::Png(format!("png encode header failed: {e}")))?;
        writer
            .write_image_data(rgb)
            .map_err(|e| SlicerV3Error::Png(format!("png encode data failed: {e}")))?;
    }
    Ok(buf)
}

/// Build a PNG thumbnail at the given target size from a base64-encoded source.
/// Returns a dithered gradient fallback when no thumbnail is provided.
pub(super) fn build_preview_png(
    base64_source: Option<&str>,
    target_w: u32,
    target_h: u32,
) -> Vec<u8> {
    if let Some(src) = base64_source.filter(|s| !s.is_empty()) {
        if let Ok(png_bytes) = decode_base64(src) {
            if let Ok((sw, sh, rgb)) = decode_png_rgb8(&png_bytes) {
                let resized = resize_rgb_nearest(sw, sh, &rgb, target_w, target_h);
                if let Ok(png) = encode_png_rgb8(target_w, target_h, &resized) {
                    return png;
                }
            }
        }
    }
    encode_png_rgb8(target_w, target_h, &gradient_preview_rgb(target_w, target_h))
        .unwrap_or_default()
}
