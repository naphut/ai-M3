#include <arm_neon.h>
#include <stdint.h>
#include <stddef.h>

extern "C" {

/**
 * High-performance ARM NEON SIMD Alpha Compositing for Video Frames.
 * Blends a premultiplied BGR overlay onto a video ROI with inverted alpha.
 * Formula per byte: frame[i] = ((frame[i] * inv_alpha[i] + 128) >> 8) + premul[i]
 * Operates on 16 bytes per instruction using 128-bit NEON registers (q-registers).
 */
void neon_blend_roi(
    uint8_t* __restrict__ frame,
    int frame_stride,
    const uint8_t* __restrict__ premul,
    const uint8_t* __restrict__ inv_alpha,
    int blend_stride,
    int width,
    int height
) {
    int total_bytes = width * 3;
    for (int y = 0; y < height; y++) {
        uint8_t* f_ptr = frame + y * frame_stride;
        const uint8_t* p_ptr = premul + y * blend_stride;
        const uint8_t* a_ptr = inv_alpha + y * blend_stride;

        int x = 0;
        // Process 16 bytes (5+ RGB pixels) per iteration with NEON
        for (; x <= total_bytes - 16; x += 16) {
            uint8x16_t f_vec = vld1q_u8(f_ptr + x);
            uint8x16_t a_vec = vld1q_u8(a_ptr + x);
            uint8x16_t p_vec = vld1q_u8(p_ptr + x);

            // Multiply: low 8 bytes and high 8 bytes -> 16-bit integers
            uint16x8_t prod_lo = vmull_u8(vget_low_u8(f_vec), vget_low_u8(a_vec));
            uint16x8_t prod_hi = vmull_u8(vget_high_u8(f_vec), vget_high_u8(a_vec));

            // Fast rounding divide by 255: vrshrn_n_u16 shifts right by 8 with rounding
            uint8x8_t res_lo = vrshrn_n_u16(prod_lo, 8);
            uint8x8_t res_hi = vrshrn_n_u16(prod_hi, 8);
            uint8x16_t scaled_f = vcombine_u8(res_lo, res_hi);

            // Saturated addition with premultiplied overlay
            uint8x16_t out_vec = vqaddq_u8(scaled_f, p_vec);
            vst1q_u8(f_ptr + x, out_vec);
        }

        // Tail processing for remaining bytes
        for (; x < total_bytes; x++) {
            uint16_t val = ((uint16_t)f_ptr[x] * (uint16_t)a_ptr[x] + 128) >> 8;
            uint16_t blended = val + p_ptr[x];
            f_ptr[x] = (blended > 255) ? 255 : (uint8_t)blended;
        }
    }
}

}
