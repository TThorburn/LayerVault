//! AFF preview thumbnails — RGB565 packed little-endian raw pixels.
//!
//! Unlike AZF (which stores PNGs inside the ZIP), AFF previews are raw
//! 16-bit-per-pixel buffers laid down right after the Preview/Preview2 table
//! headers. Pack format: R5 (high), G6 (mid), B5 (low), little-endian.
//!
//! When no thumbnail PNG is provided by the job, a dithered diagonal gradient
//! (dark purple → dark green, matching CTB/Elegoo) is generated as a fallback.

use super::anycubic_preview_common::{decode_base64, decode_png_rgb8, gradient_preview_rgb, resize_rgb_nearest};

pub(super) fn pack_rgb565_le(rgb: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(rgb.len() / 3 * 2);
    for px in rgb.chunks_exact(3) {
        let r5 = (px[0] >> 3) as u16;
        let g6 = (px[1] >> 2) as u16;
        let b5 = (px[2] >> 3) as u16;
        let word = (r5 << 11) | (g6 << 5) | b5;
        out.extend_from_slice(&word.to_le_bytes());
    }
    out
}

/// Decode the base64-encoded PNG thumbnail in the job, resize it to the
/// requested dimensions, and pack as RGB565 little-endian.
/// Returns a dithered gradient fallback when no thumbnail is provided.
pub(super) fn build_preview_rgb565(
    base64_source: Option<&str>,
    target_w: u32,
    target_h: u32,
) -> Vec<u8> {
    if let Some(src) = base64_source.filter(|s| !s.is_empty()) {
        if let Ok(png_bytes) = decode_base64(src) {
            if let Ok((sw, sh, rgb)) = decode_png_rgb8(&png_bytes) {
                let resized = resize_rgb_nearest(sw, sh, &rgb, target_w, target_h);
                return pack_rgb565_le(&resized);
            }
        }
    }
    pack_rgb565_le(&gradient_preview_rgb(target_w, target_h))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rgb565_packs_pure_red() {
        // RGB (255, 0, 0) -> r5=31, g6=0, b5=0 -> 0xF800 -> LE bytes [0x00, 0xF8]
        let out = pack_rgb565_le(&[255, 0, 0]);
        assert_eq!(out, vec![0x00, 0xF8]);
    }

    #[test]
    fn rgb565_packs_pure_green() {
        // RGB (0, 255, 0) -> r5=0, g6=63, b5=0 -> 0x07E0 -> LE bytes [0xE0, 0x07]
        let out = pack_rgb565_le(&[0, 255, 0]);
        assert_eq!(out, vec![0xE0, 0x07]);
    }

    #[test]
    fn rgb565_packs_pure_blue() {
        // RGB (0, 0, 255) -> r5=0, g6=0, b5=31 -> 0x001F -> LE bytes [0x1F, 0x00]
        let out = pack_rgb565_le(&[0, 0, 255]);
        assert_eq!(out, vec![0x1F, 0x00]);
    }

    #[test]
    fn rgb565_packs_white_black_pair() {
        // White (255,255,255) -> 0xFFFF -> [0xFF, 0xFF]
        // Black (0,0,0)       -> 0x0000 -> [0x00, 0x00]
        let out = pack_rgb565_le(&[255, 255, 255, 0, 0, 0]);
        assert_eq!(out, vec![0xFF, 0xFF, 0x00, 0x00]);
    }
}
