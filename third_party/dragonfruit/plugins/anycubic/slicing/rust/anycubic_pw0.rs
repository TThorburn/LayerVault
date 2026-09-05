//! PW0 run-length encoding for Anycubic layer images.
//!
//! PW0 uses 4-bit colour quantisation (16 grey levels).
//!
//! Encoding rules:
//! - Each pixel is quantised to `colour = byte >> 4` (0x0..0xF).
//! - **Black (0x0) or white (0xF)**: 2-byte big-endian encoding
//!   `[colour_nibble << 12 | repeat]` with max repeat 4095.
//! - **Grey (0x1..0xE)**: 1-byte encoding `[colour_nibble << 4 | repeat]`
//!   with max repeat 15.

const RLE4_ENCODING_LIMIT: u16 = 0xFFF; // 4095

#[inline]
fn flush_run(out: &mut Vec<u8>, colour: u8, reps: &mut u32) {
    while *reps > 0 {
        if colour == 0x0 || colour == 0xF {
            let done = (*reps).min(RLE4_ENCODING_LIMIT as u32);
            let word = (done as u16) | ((colour as u16) << 12);
            out.push((word >> 8) as u8);
            out.push(word as u8);
            *reps -= done;
        } else {
            let done = (*reps).min(0xF);
            out.push((done as u8) | (colour << 4));
            *reps -= done;
        }
    }
}

/// Encode a raw 8-bit greyscale mask into PW0 RLE bytes.
pub(super) fn encode_pw0(mask: &[u8]) -> Vec<u8> {
    let mut out: Vec<u8> = Vec::with_capacity(mask.len() / 4);
    let mut last_colour: i32 = -1;
    let mut reps: u32 = 0;

    for &byte in mask {
        let colour = (byte >> 4) as i32;
        if colour == last_colour {
            reps += 1;
        } else {
            if last_colour >= 0 {
                flush_run(&mut out, last_colour as u8, &mut reps);
            }
            last_colour = colour;
            reps = 1;
        }
    }
    if last_colour >= 0 {
        flush_run(&mut out, last_colour as u8, &mut reps);
    }

    out
}

/// Decode PW0 RLE bytes back into a flat 8-bit greyscale pixel buffer of
/// length `expected_pixels`. Quantisation is 4-bit, so the original 0..255
/// range is reconstructed by nibble-doubling (`(colour << 4) | colour`),
/// matching the convention used for HTML colour shorthand expansion.
pub(super) fn decode_pw0(data: &[u8], expected_pixels: usize) -> Vec<u8> {
    let mut pixels = Vec::with_capacity(expected_pixels);
    let mut i = 0;

    while i < data.len() && pixels.len() < expected_pixels {
        let b0 = data[i];
        i += 1;
        let colour = b0 >> 4;

        let repeat: u32 = if colour == 0x0 || colour == 0xF {
            // 2-byte big-endian long-run encoding
            if i >= data.len() {
                break;
            }
            let b1 = data[i];
            i += 1;
            (((b0 & 0x0F) as u32) << 8) | (b1 as u32)
        } else {
            // 1-byte short-run encoding (grey 0x1..0xE), max 15 reps
            (b0 & 0x0F) as u32
        };

        let value = (colour << 4) | colour;
        let remaining = expected_pixels - pixels.len();
        let fill = (repeat as usize).min(remaining);
        for _ in 0..fill {
            pixels.push(value);
        }
    }

    pixels.resize(expected_pixels, 0);
    pixels
}

/// Encode rasterized row-major RLE runs directly into PW0 bytes.
pub(super) fn encode_pw0_from_rle(
    runs: &[crate::rle::RleRun],
    total_pixels: usize,
) -> Vec<u8> {
    let mut out: Vec<u8> = Vec::with_capacity(total_pixels / 4);

    if runs.is_empty() {
        let mut remaining = total_pixels as u32;
        flush_run(&mut out, 0, &mut remaining);
        return out;
    }

    let mut last_colour: Option<u8> = None;
    let mut reps: u32 = 0;
    let mut emitted_pixels = 0usize;

    for run in runs {
        let colour = run.value >> 4;
        let run_len = run.length as usize;
        let available = total_pixels.saturating_sub(emitted_pixels);
        let to_emit = run_len.min(available) as u32;
        if to_emit == 0 {
            break;
        }

        if last_colour == Some(colour) {
            reps = reps.saturating_add(to_emit);
        } else {
            if let Some(prev_colour) = last_colour {
                flush_run(&mut out, prev_colour, &mut reps);
            }
            last_colour = Some(colour);
            reps = to_emit;
        }
        emitted_pixels = emitted_pixels.saturating_add(to_emit as usize);
    }

    if let Some(colour) = last_colour {
        flush_run(&mut out, colour, &mut reps);
    }

    let trailing_zeros = total_pixels.saturating_sub(emitted_pixels) as u32;
    if trailing_zeros > 0 {
        let mut remaining = trailing_zeros;
        flush_run(&mut out, 0, &mut remaining);
    }

    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encode_all_black() {
        let mask = vec![0u8; 100];
        let encoded = encode_pw0(&mask);
        // Black run of 100: 0x0064
        assert_eq!(encoded, vec![0x00, 100]);
    }

    #[test]
    fn encode_all_white() {
        let mask = vec![255u8; 100];
        let encoded = encode_pw0(&mask);
        // White run of 100: 0xF064
        assert_eq!(encoded, vec![0xF0, 100]);
    }

    #[test]
    fn encode_grey_limited_to_15_reps() {
        // Grey colour 0x8 (pixel value 0x80..0x8F) with 20 reps
        let mask = vec![0x88u8; 20];
        let encoded = encode_pw0(&mask);
        // 15 reps + 5 reps
        assert_eq!(encoded, vec![0x8F, 0x85]);
    }

    #[test]
    fn encode_mixed() {
        // 3 black, 2 white
        let mask = vec![0, 0, 0, 255, 255];
        let encoded = encode_pw0(&mask);
        assert_eq!(encoded, vec![0x00, 3, 0xF0, 2]);
    }

    #[test]
    fn encode_long_black_run_above_4095() {
        let mask = vec![0u8; 5000];
        let encoded = encode_pw0(&mask);
        // 4095 + 905 = 0x0FFF then 0x0389
        assert_eq!(
            encoded,
            vec![0x0F, 0xFF, 0x03, 0x89]
        );
    }

    #[test]
    fn encode_rle_matches_mask_encoding() {
        let mask = vec![0, 0, 0x88, 0x88, 0x88, 255, 255, 0, 0];
        let runs = vec![
            crate::rle::RleRun {
                length: 2,
                value: 0,
            },
            crate::rle::RleRun {
                length: 3,
                value: 0x88,
            },
            crate::rle::RleRun {
                length: 2,
                value: 255,
            },
            crate::rle::RleRun {
                length: 2,
                value: 0,
            },
        ];

        assert_eq!(encode_pw0(&mask), encode_pw0_from_rle(&runs, mask.len()));
    }

    #[test]
    fn encode_empty_rle_layer_as_black() {
        let encoded = encode_pw0_from_rle(&[], 100);
        assert_eq!(encoded, vec![0x00, 100]);
    }

    #[test]
    fn encode_rle_pads_truncated_input_with_black() {
        let runs = vec![crate::rle::RleRun {
            length: 3,
            value: 255,
        }];
        let encoded = encode_pw0_from_rle(&runs, 5);
        assert_eq!(encoded, vec![0xF0, 3, 0x00, 2]);
    }

    #[test]
    fn decode_round_trips_all_black() {
        let encoded = encode_pw0(&vec![0u8; 100]);
        assert_eq!(decode_pw0(&encoded, 100), vec![0u8; 100]);
    }

    #[test]
    fn decode_round_trips_all_white() {
        // 0xFF quantises to colour 0xF, nibble-doubled back to 0xFF.
        let encoded = encode_pw0(&vec![0xFFu8; 100]);
        assert_eq!(decode_pw0(&encoded, 100), vec![0xFFu8; 100]);
    }

    #[test]
    fn decode_round_trips_grey_runs_above_15() {
        // Grey 0x88 round-trips exactly under nibble-doubling.
        let mask = vec![0x88u8; 50];
        let encoded = encode_pw0(&mask);
        assert_eq!(decode_pw0(&encoded, 50), mask);
    }

    #[test]
    fn decode_round_trips_mixed_palette() {
        // Each value has low_nibble == high_nibble so quantisation is lossless.
        let mask = vec![0x00, 0x00, 0x88, 0x88, 0x88, 0xFF, 0xFF, 0x00, 0x00];
        let encoded = encode_pw0(&mask);
        assert_eq!(decode_pw0(&encoded, mask.len()), mask);
    }

    #[test]
    fn decode_round_trips_long_run_above_4095() {
        let mask = vec![0u8; 5000];
        let encoded = encode_pw0(&mask);
        assert_eq!(decode_pw0(&encoded, 5000), mask);
    }

    #[test]
    fn decode_pads_short_input_with_black() {
        // Encoded buffer covers fewer pixels than requested.
        let encoded = vec![0xF0, 3]; // 3 white pixels
        let pixels = decode_pw0(&encoded, 5);
        assert_eq!(pixels, vec![0xFF, 0xFF, 0xFF, 0x00, 0x00]);
    }

    #[test]
    fn decode_truncates_overlong_input() {
        // Encoded run claims 10 pixels but caller only wants 3.
        let encoded = vec![0xF0, 10];
        let pixels = decode_pw0(&encoded, 3);
        assert_eq!(pixels, vec![0xFF, 0xFF, 0xFF]);
    }
}
