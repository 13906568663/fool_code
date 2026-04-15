use pyo3::prelude::*;
use pyo3::types::PyDict;
use windows::Win32::Foundation::*;
use windows::Win32::Graphics::Gdi::*;
use windows::Win32::UI::HiDpi::*;

struct MonitorInfo {
    handle: isize,
    left: i32,
    top: i32,
    width: i32,
    height: i32,
    scale_factor: f64,
}

unsafe extern "system" fn enum_monitors_callback(
    hmonitor: HMONITOR,
    _hdc: HDC,
    _lprect: *mut RECT,
    lparam: LPARAM,
) -> BOOL {
    let monitors = &mut *(lparam.0 as *mut Vec<MonitorInfo>);

    let mut mi = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    if GetMonitorInfoW(hmonitor, &mut mi).as_bool() {
        let rc = mi.rcMonitor;
        let w = rc.right - rc.left;
        let h = rc.bottom - rc.top;

        let mut dpi_x: u32 = 96;
        let mut dpi_y: u32 = 96;
        let _ = GetDpiForMonitor(hmonitor, MDT_EFFECTIVE_DPI, &mut dpi_x, &mut dpi_y);
        let scale = dpi_x as f64 / 96.0;

        monitors.push(MonitorInfo {
            handle: hmonitor.0 as isize,
            left: rc.left,
            top: rc.top,
            width: w,
            height: h,
            scale_factor: scale,
        });
    }
    TRUE
}

fn enumerate_monitors() -> Vec<MonitorInfo> {
    let mut monitors: Vec<MonitorInfo> = Vec::new();
    unsafe {
        let _ = EnumDisplayMonitors(
            None,
            None,
            Some(enum_monitors_callback),
            LPARAM(&mut monitors as *mut Vec<MonitorInfo> as isize),
        );
    }
    monitors
}

fn monitor_to_dict<'py>(py: Python<'py>, m: &MonitorInfo) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("display_id", m.handle)?;
    d.set_item("width", m.width)?;
    d.set_item("height", m.height)?;
    d.set_item("scale_factor", m.scale_factor)?;
    d.set_item("origin_x", m.left)?;
    d.set_item("origin_y", m.top)?;
    Ok(d)
}

/// Get geometry of the primary display.
#[pyfunction]
pub fn get_display_size(py: Python<'_>) -> PyResult<PyObject> {
    let monitors = enumerate_monitors();
    let primary = monitors.into_iter().find(|m| m.left == 0 && m.top == 0);
    match primary {
        Some(m) => Ok(monitor_to_dict(py, &m)?.into()),
        None => Err(pyo3::exceptions::PyRuntimeError::new_err("No primary display found")),
    }
}

/// List all displays with geometry info.
#[pyfunction]
pub fn list_displays(py: Python<'_>) -> PyResult<Vec<PyObject>> {
    let monitors = enumerate_monitors();
    monitors
        .iter()
        .map(|m| Ok(monitor_to_dict(py, m)?.into()))
        .collect()
}
