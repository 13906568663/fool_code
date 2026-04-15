use base64::Engine;
use image::codecs::jpeg::JpegEncoder;
use pyo3::prelude::*;
use std::io::Cursor;
use windows::Win32::Graphics::Gdi::*;
use windows::Win32::UI::HiDpi::*;
use windows::Win32::UI::WindowsAndMessaging::*;

/// RAII guard: sets per-monitor DPI awareness on the current thread,
/// restores the previous context when dropped.
struct DpiAwareGuard {
    prev: DPI_AWARENESS_CONTEXT,
}

impl DpiAwareGuard {
    fn new() -> Self {
        let prev = unsafe {
            SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        };
        Self { prev }
    }
}

impl Drop for DpiAwareGuard {
    fn drop(&mut self) {
        unsafe {
            SetThreadDpiAwarenessContext(self.prev);
        }
    }
}

fn capture_screen_gdi(
    x: i32,
    y: i32,
    width: i32,
    height: i32,
) -> Result<(Vec<u8>, i32, i32), String> {
    unsafe {
        let hdc_screen = GetDC(None);
        if hdc_screen.is_invalid() {
            return Err("GetDC failed".into());
        }
        let hdc_mem = CreateCompatibleDC(hdc_screen);
        if hdc_mem.is_invalid() {
            ReleaseDC(None, hdc_screen);
            return Err("CreateCompatibleDC failed".into());
        }
        let hbm = CreateCompatibleBitmap(hdc_screen, width, height);
        if hbm.is_invalid() {
            let _ = DeleteDC(hdc_mem);
            ReleaseDC(None, hdc_screen);
            return Err("CreateCompatibleBitmap failed".into());
        }
        let old = SelectObject(hdc_mem, hbm);

        let ok = BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, x, y, SRCCOPY);
        if ok.is_err() {
            SelectObject(hdc_mem, old);
            let _ = DeleteObject(hbm);
            let _ = DeleteDC(hdc_mem);
            ReleaseDC(None, hdc_screen);
            return Err("BitBlt failed".into());
        }

        let mut bmi = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: width,
                biHeight: -height, // top-down
                biPlanes: 1,
                biBitCount: 32,
                biCompression: 0, // BI_RGB
                ..Default::default()
            },
            ..Default::default()
        };

        let buf_size = (width * height * 4) as usize;
        let mut buf = vec![0u8; buf_size];
        let lines = GetDIBits(
            hdc_mem,
            hbm,
            0,
            height as u32,
            Some(buf.as_mut_ptr() as *mut _),
            &mut bmi,
            DIB_RGB_COLORS,
        );

        SelectObject(hdc_mem, old);
        let _ = DeleteObject(hbm);
        let _ = DeleteDC(hdc_mem);
        ReleaseDC(None, hdc_screen);

        if lines == 0 {
            return Err("GetDIBits failed".into());
        }

        // BGRA -> RGB
        let pixel_count = (width * height) as usize;
        let mut rgb = Vec::with_capacity(pixel_count * 3);
        for i in 0..pixel_count {
            let off = i * 4;
            rgb.push(buf[off + 2]); // R
            rgb.push(buf[off + 1]); // G
            rgb.push(buf[off]);     // B
        }

        Ok((rgb, width, height))
    }
}

fn encode_jpeg_base64(rgb: &[u8], width: u32, height: u32, quality: u8) -> Result<String, String> {
    let mut jpeg_buf = Cursor::new(Vec::new());
    let encoder = JpegEncoder::new_with_quality(&mut jpeg_buf, quality);
    image::ImageEncoder::write_image(
        encoder,
        rgb,
        width,
        height,
        image::ExtendedColorType::Rgb8,
    )
    .map_err(|e| format!("JPEG encode error: {e}"))?;

    Ok(base64::engine::general_purpose::STANDARD.encode(jpeg_buf.into_inner()))
}

/// Get the DPI scale factor for the primary monitor (physical / logical).
fn get_dpi_scale() -> f64 {
    let logical_w = unsafe { GetSystemMetrics(SM_CXSCREEN) } as f64;
    let _guard = DpiAwareGuard::new();
    let physical_w = unsafe { GetSystemMetrics(SM_CXSCREEN) } as f64;
    if logical_w > 0.0 { physical_w / logical_w } else { 1.0 }
}

/// Capture the entire primary screen at full physical resolution.
/// Returns (base64_jpeg, logical_width, logical_height).
/// The image data is at physical resolution for maximum quality;
/// the returned dimensions are logical (for coordinate mapping with mouse input).
#[pyfunction]
#[pyo3(signature = (quality=75))]
pub fn screenshot(quality: u8) -> PyResult<(String, i32, i32)> {
    let logical_w = unsafe { GetSystemMetrics(SM_CXSCREEN) };
    let logical_h = unsafe { GetSystemMetrics(SM_CYSCREEN) };

    let (rgb, phys_w, phys_h) = {
        let _guard = DpiAwareGuard::new();
        let pw = unsafe { GetSystemMetrics(SM_CXSCREEN) };
        let ph = unsafe { GetSystemMetrics(SM_CYSCREEN) };
        capture_screen_gdi(0, 0, pw, ph)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?
    };

    let b64 = encode_jpeg_base64(&rgb, phys_w as u32, phys_h as u32, quality)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;

    Ok((b64, logical_w, logical_h))
}

/// Capture a screen region at full physical resolution.
/// (x, y, w, h) are in **logical** screen coordinates.
/// Returns (base64_jpeg, captured_physical_w, captured_physical_h).
#[pyfunction]
#[pyo3(signature = (x, y, w, h, quality=75))]
pub fn screenshot_region(x: i32, y: i32, w: i32, h: i32, quality: u8) -> PyResult<(String, i32, i32)> {
    if w <= 0 || h <= 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("width and height must be positive"));
    }

    let scale = get_dpi_scale();
    let px = (x as f64 * scale).round() as i32;
    let py = (y as f64 * scale).round() as i32;
    let pw = (w as f64 * scale).round() as i32;
    let ph = (h as f64 * scale).round() as i32;

    let (rgb, rw, rh) = {
        let _guard = DpiAwareGuard::new();
        capture_screen_gdi(px, py, pw, ph)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?
    };

    let b64 = encode_jpeg_base64(&rgb, rw as u32, rh as u32, quality)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;

    Ok((b64, rw, rh))
}
