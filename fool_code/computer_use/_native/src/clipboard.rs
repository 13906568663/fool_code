use pyo3::prelude::*;
use windows::Win32::Foundation::HGLOBAL;
use windows::Win32::System::DataExchange::*;
use windows::Win32::System::Memory::*;
use windows::Win32::System::Ole::CF_UNICODETEXT;

/// Read text from the Windows clipboard.
#[pyfunction]
pub fn read_clipboard() -> PyResult<String> {
    unsafe {
        if OpenClipboard(None).is_err() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err("OpenClipboard failed"));
        }
        let result = (|| -> Result<String, String> {
            let h = GetClipboardData(CF_UNICODETEXT.0 as u32);
            let h = match h {
                Ok(h) if !h.0.is_null() => h,
                _ => return Ok(String::new()),
            };
            let hglobal = HGLOBAL(h.0);
            let ptr = GlobalLock(hglobal) as *const u16;
            if ptr.is_null() {
                return Err("GlobalLock failed".into());
            }
            let mut len = 0usize;
            while *ptr.add(len) != 0 {
                len += 1;
            }
            let slice = std::slice::from_raw_parts(ptr, len);
            let text = String::from_utf16_lossy(slice);
            let _ = GlobalUnlock(hglobal);
            Ok(text)
        })();
        let _ = CloseClipboard();
        result.map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }
}

/// Write text to the Windows clipboard.
#[pyfunction]
pub fn write_clipboard(text: &str) -> PyResult<()> {
    let wide: Vec<u16> = text.encode_utf16().chain(std::iter::once(0)).collect();
    let byte_len = wide.len() * 2;

    unsafe {
        if OpenClipboard(None).is_err() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err("OpenClipboard failed"));
        }
        let result = (|| -> Result<(), String> {
            EmptyClipboard().map_err(|e| format!("EmptyClipboard: {e}"))?;
            let hmem = GlobalAlloc(GMEM_MOVEABLE, byte_len).map_err(|e| format!("GlobalAlloc: {e}"))?;
            let ptr = GlobalLock(hmem) as *mut u16;
            if ptr.is_null() {
                return Err("GlobalLock failed".into());
            }
            std::ptr::copy_nonoverlapping(wide.as_ptr(), ptr, wide.len());
            let _ = GlobalUnlock(hmem);
            SetClipboardData(CF_UNICODETEXT.0 as u32, windows::Win32::Foundation::HANDLE(hmem.0))
                .map_err(|e| format!("SetClipboardData: {e}"))?;
            Ok(())
        })();
        let _ = CloseClipboard();
        result.map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }
}
