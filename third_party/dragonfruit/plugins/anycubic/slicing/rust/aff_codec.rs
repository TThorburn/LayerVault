//! AFF RLE codec dispatcher.
//!
//! PW0 (4-bit greyscale, used by 20 extensions) is re-exported from
//! `anycubic_pw0`. PWS (multi-pass 1-bit threshold for anti-aliasing,
//! used only by `.pws`) is implemented here.

pub(super) use super::anycubic_pw0::encode_pw0_from_rle;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum AffRleFormat {
    Pw0,
    Pws,
}

pub(super) fn aff_rle_format_for_suffix(suffix: &str) -> AffRleFormat {
    if suffix.eq_ignore_ascii_case("pws") {
        AffRleFormat::Pws
    } else {
        AffRleFormat::Pw0
    }
}

const RLE1_ENCODING_LIMIT: u8 = 125; // 0x7D — same as UVTools

pub(super) fn encode_pws(mask: &[u8], aa_level: u8) -> Vec<u8> {
    let aa = aa_level.clamp(1, 16);
    let mut out: Vec<u8> = Vec::with_capacity(mask.len() / 4);

    for level in 1..=aa {
        let threshold: u8 = ((255u32 * level as u32) / (aa as u32 + 1) + 1) as u8;
        let mut obit = false;
        let mut rep: u8 = 0;

        let flush = |out: &mut Vec<u8>, obit: bool, rep: u8| {
            if rep == 0 {
                return;
            }
            let mut byte = rep;
            if obit {
                byte |= 0x80;
            }
            out.push(byte);
        };

        for &pixel in mask {
            let nbit = pixel >= threshold;

            if nbit == obit {
                rep += 1;
                if rep == RLE1_ENCODING_LIMIT {
                    flush(&mut out, obit, rep);
                    rep = 0;
                }
            } else {
                flush(&mut out, obit, rep);
                obit = nbit;
                rep = 1;
            }
        }

        flush(&mut out, obit, rep);
    }

    out
}

#[cfg(test)]
pub(super) fn decode_pws(data: &[u8], expected_pixels: usize, aa_level: u8) -> Vec<u8> {
    let aa = aa_level.clamp(1, 16);
    let mut counts: Vec<u8> = vec![0u8; expected_pixels];
    let mut index = 0usize;

    for _level in 0..aa {
        let mut pixel = 0usize;
        while index < data.len() && pixel < expected_pixels {
            let b = data[index];
            index += 1;
            let reps = (b & 0x7F) as usize;
            let is_white = (b & 0x80) != 0;

            for i in 0..reps {
                if pixel + i >= expected_pixels {
                    break;
                }
                if is_white {
                    counts[pixel + i] = counts[pixel + i].saturating_add(1);
                }
            }
            pixel += reps;
            if pixel >= expected_pixels {
                break;
            }
        }
    }

    // Map AA counts back to 0..255 using same scaling UVTools applies:
    // newC = count * (256 / AA); subtract 1 if non-zero
    counts
        .into_iter()
        .map(|c| {
            let scaled = (c as u32) * (256 / aa as u32);
            if scaled == 0 {
                0u8
            } else {
                (scaled - 1) as u8
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pws_round_trip_aa1_all_black() {
        let mask = vec![0u8; 100];
        let encoded = encode_pws(&mask, 1);
        let decoded = decode_pws(&encoded, mask.len(), 1);
        assert_eq!(decoded, mask);
    }

    #[test]
    fn pws_round_trip_aa1_all_white() {
        let mask = vec![255u8; 100];
        let encoded = encode_pws(&mask, 1);
        let decoded = decode_pws(&encoded, mask.len(), 1);
        assert_eq!(decoded, mask);
    }

    #[test]
    fn pws_round_trip_aa4_mixed() {
        // 256 pixels covering full intensity range, AA=4 emits 4 RLE passes
        let mask: Vec<u8> = (0..=255u8).chain(0..=255u8).take(256).collect();
        let encoded = encode_pws(&mask, 4);
        let decoded = decode_pws(&encoded, mask.len(), 4);
        assert_eq!(decoded.len(), mask.len());
        for (orig, dec) in mask.iter().zip(decoded.iter()) {
            if *orig == 0 {
                assert_eq!(*dec, 0);
            }
            if *orig == 255 {
                assert_eq!(*dec, 255);
            }
        }
    }

    #[test]
    fn pws_long_run_emits_multiple_segments() {
        // 200 black pixels should split across multiple RLE bytes (cap = 125)
        let mask = vec![0u8; 200];
        let encoded = encode_pws(&mask, 1);
        assert!(encoded.len() >= 2);
        let decoded = decode_pws(&encoded, mask.len(), 1);
        assert_eq!(decoded, mask);
    }
}
