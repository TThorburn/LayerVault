//! Shared preview thumbnail helpers used by both AFF and AZF encoders.
//!
//! Both formats accept a base64-encoded PNG thumbnail from the job, decode it,
//! and resize it to a target dimension. Only the final pack format differs
//! (AZF re-encodes as PNG; AFF packs as raw RGB565 little-endian).
//!
//! When no thumbnail is provided, a dithered diagonal gradient (dark purple →
//! dark green) is generated as a fallback, matching CTB/Elegoo behaviour.

use crate::engine::SlicerV3Error;
use base64::Engine;
use std::io::Cursor;

/// Decode a base64 string that may be either a plain base64 blob or a
/// `data:image/png;base64,...` data-URL.
pub(super) fn decode_base64(input: &str) -> Result<Vec<u8>, SlicerV3Error> {
    let payload = input
        .split_once(',')
        .map(|(_, rhs)| rhs)
        .unwrap_or(input)
        .trim();

    base64::engine::general_purpose::STANDARD
        .decode(payload)
        .map_err(|e| SlicerV3Error::Png(format!("invalid base64 preview payload: {e}")))
}

/// Decode PNG bytes into (width, height, RGB8 pixels).
pub(super) fn decode_png_rgb8(png_bytes: &[u8]) -> Result<(u32, u32, Vec<u8>), SlicerV3Error> {
    let cursor = Cursor::new(png_bytes);
    let mut decoder = png::Decoder::new(cursor);
    decoder.set_transformations(png::Transformations::EXPAND | png::Transformations::STRIP_16);

    let mut reader = decoder
        .read_info()
        .map_err(|e| SlicerV3Error::Png(format!("png decode header failed: {e}")))?;

    let mut buf = vec![0u8; reader.output_buffer_size()];
    let info = reader
        .next_frame(&mut buf)
        .map_err(|e| SlicerV3Error::Png(format!("png decode frame failed: {e}")))?;

    let src = &buf[..info.buffer_size()];
    let mut out = Vec::with_capacity((info.width as usize) * (info.height as usize) * 3);

    match info.color_type {
        png::ColorType::Rgb => out.extend_from_slice(src),
        png::ColorType::Rgba => {
            for px in src.chunks_exact(4) {
                out.push(px[0]);
                out.push(px[1]);
                out.push(px[2]);
            }
        }
        png::ColorType::Grayscale => {
            for &g in src {
                out.push(g);
                out.push(g);
                out.push(g);
            }
        }
        png::ColorType::GrayscaleAlpha => {
            for px in src.chunks_exact(2) {
                out.push(px[0]);
                out.push(px[0]);
                out.push(px[0]);
            }
        }
        _ => {
            return Err(SlicerV3Error::Png(
                "unsupported PNG colour type for preview".to_string(),
            ));
        }
    }

    Ok((info.width, info.height, out))
}

/// Nearest-neighbour resize of an RGB8 buffer.
pub(super) fn resize_rgb_nearest(
    src_w: u32,
    src_h: u32,
    src: &[u8],
    dst_w: u32,
    dst_h: u32,
) -> Vec<u8> {
    if src_w == dst_w && src_h == dst_h {
        return src.to_vec();
    }
    let mut out = vec![0u8; (dst_w as usize) * (dst_h as usize) * 3];
    for y in 0..dst_h {
        let sy = ((y as u64) * (src_h as u64) / (dst_h as u64)) as usize;
        for x in 0..dst_w {
            let sx = ((x as u64) * (src_w as u64) / (dst_w as u64)) as usize;
            let si = (sy * src_w as usize + sx) * 3;
            let di = (y as usize * dst_w as usize + x as usize) * 3;
            out[di..di + 3].copy_from_slice(&src[si..si + 3]);
        }
    }
    out
}

/// Generate a dithered diagonal gradient fallback preview (RGB888).
/// Dark dragonfruit purple → dark dragonfruit green, Bayer 4×4 dithering.
pub(super) fn gradient_preview_rgb(w: u32, h: u32) -> Vec<u8> {
    let gradient_start = [32u32, 10u32, 42u32];
    let gradient_end = [14u32, 34u32, 14u32];
    let bayer4x4: [[i32; 4]; 4] = [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ];

    let dither_u8 = |v: u32, d: i32| -> u8 {
        let offset = (d - 8) * 3 / 8;
        (v as i32 + offset).clamp(0, 255) as u8
    };

    let denom = (w as u64 + h as u64).max(1);
    let mut out = Vec::with_capacity((w * h * 3) as usize);

    for y in 0..h {
        for x in 0..w {
            let dither = bayer4x4[(y as usize) & 3][(x as usize) & 3];
            let t = ((x as u64 + y as u64) * 255 / denom) as u32;
            let r = ((gradient_start[0] * (255 - t) + gradient_end[0] * t) / 255) as u32;
            let g = ((gradient_start[1] * (255 - t) + gradient_end[1] * t) / 255) as u32;
            let b = ((gradient_start[2] * (255 - t) + gradient_end[2] * t) / 255) as u32;
            out.push(dither_u8(r, dither));
            out.push(dither_u8(g, dither));
            out.push(dither_u8(b, dither));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resize_passthrough_when_same_size() {
        let src = vec![1u8, 2, 3, 4, 5, 6]; // 2x1 RGB
        let out = resize_rgb_nearest(2, 1, &src, 2, 1);
        assert_eq!(out, src);
    }

    #[test]
    fn resize_doubles_width() {
        let src = vec![10u8, 20, 30, 40, 50, 60]; // 2x1 RGB pixels (10,20,30) and (40,50,60)
        let out = resize_rgb_nearest(2, 1, &src, 4, 1);
        // Nearest-neighbour: x=0->src.0, x=1->src.0, x=2->src.1, x=3->src.1
        assert_eq!(out, vec![10, 20, 30, 10, 20, 30, 40, 50, 60, 40, 50, 60]);
    }
}
