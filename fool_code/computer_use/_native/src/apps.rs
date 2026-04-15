use pyo3::prelude::*;
use pyo3::types::PyDict;
use windows::Win32::Foundation::*;
use windows::Win32::System::Diagnostics::ToolHelp::*;
use windows::Win32::System::Registry::*;
use windows::Win32::System::Threading::*;
use windows::Win32::UI::Shell::ShellExecuteW;
use windows::Win32::UI::WindowsAndMessaging::*;
use windows::core::{PCWSTR, PWSTR};

fn get_process_exe(pid: u32) -> Option<String> {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let mut buf = [0u16; 1024];
        let mut size = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(handle, PROCESS_NAME_WIN32, PWSTR(buf.as_mut_ptr()), &mut size);
        let _ = CloseHandle(handle);
        if ok.is_ok() {
            Some(String::from_utf16_lossy(&buf[..size as usize]))
        } else {
            None
        }
    }
}

fn get_window_title(hwnd: HWND) -> String {
    unsafe {
        let len = GetWindowTextLengthW(hwnd);
        if len == 0 {
            return String::new();
        }
        let mut buf = vec![0u16; (len + 1) as usize];
        GetWindowTextW(hwnd, &mut buf);
        String::from_utf16_lossy(&buf[..len as usize])
    }
}

/// Get info about the foreground window: {exe, title, pid}.
#[pyfunction]
pub fn get_foreground_app(py: Python<'_>) -> PyResult<Option<PyObject>> {
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.0 == std::ptr::null_mut() {
            return Ok(None);
        }
        let mut pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));

        let d = PyDict::new(py);
        d.set_item("pid", pid)?;
        d.set_item("title", get_window_title(hwnd))?;
        d.set_item("exe", get_process_exe(pid).unwrap_or_default())?;
        Ok(Some(d.into()))
    }
}

/// List running processes: [{pid, name, exe}].
#[pyfunction]
pub fn list_running_apps(py: Python<'_>) -> PyResult<Vec<PyObject>> {
    let mut result = Vec::new();
    unsafe {
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Snapshot: {e}")))?;

        let mut entry = PROCESSENTRY32W {
            dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };

        if Process32FirstW(snap, &mut entry).is_ok() {
            loop {
                let name_len = entry.szExeFile.iter().position(|&c| c == 0).unwrap_or(entry.szExeFile.len());
                let name = String::from_utf16_lossy(&entry.szExeFile[..name_len]);
                let pid = entry.th32ProcessID;

                let d = PyDict::new(py);
                d.set_item("pid", pid)?;
                d.set_item("name", &name)?;
                d.set_item("exe", get_process_exe(pid).unwrap_or_default())?;
                result.push(d.into());

                if Process32NextW(snap, &mut entry).is_err() {
                    break;
                }
            }
        }
        let _ = CloseHandle(snap);
    }
    Ok(result)
}

fn read_reg_string(hkey: HKEY, value: &str) -> Option<String> {
    unsafe {
        let wide_name: Vec<u16> = value.encode_utf16().chain(std::iter::once(0)).collect();
        let mut buf_size: u32 = 0;
        let mut kind = REG_VALUE_TYPE::default();
        let status = RegQueryValueExW(
            hkey,
            PCWSTR(wide_name.as_ptr()),
            None,
            Some(&mut kind),
            None,
            Some(&mut buf_size),
        );
        if status.is_err() || buf_size == 0 || kind != REG_SZ {
            return None;
        }
        let mut buf = vec![0u8; buf_size as usize];
        let status = RegQueryValueExW(
            hkey,
            PCWSTR(wide_name.as_ptr()),
            None,
            None,
            Some(buf.as_mut_ptr()),
            Some(&mut buf_size),
        );
        if status.is_err() {
            return None;
        }
        let wide: &[u16] = std::slice::from_raw_parts(buf.as_ptr() as *const u16, buf_size as usize / 2);
        let len = wide.iter().position(|&c| c == 0).unwrap_or(wide.len());
        Some(String::from_utf16_lossy(&wide[..len]))
    }
}

/// List installed applications from registry.
#[pyfunction]
pub fn list_installed_apps(py: Python<'_>) -> PyResult<Vec<PyObject>> {
    let mut apps = Vec::new();
    let paths: &[(&str, HKEY)] = &[
        (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", HKEY_LOCAL_MACHINE),
        (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", HKEY_CURRENT_USER),
    ];

    for &(path, root) in paths {
        unsafe {
            let wide_path: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
            let mut hkey = HKEY::default();
            if RegOpenKeyExW(root, PCWSTR(wide_path.as_ptr()), 0, KEY_READ, &mut hkey).is_err() {
                continue;
            }
            let mut index = 0u32;
            loop {
                let mut name_buf = [0u16; 512];
                let mut name_len = name_buf.len() as u32;
                let status = RegEnumKeyExW(hkey, index, PWSTR(name_buf.as_mut_ptr()), &mut name_len, None, PWSTR::null(), None, None);
                if status.is_err() {
                    break;
                }
                index += 1;

                let mut subkey = HKEY::default();
                if RegOpenKeyExW(hkey, PCWSTR(name_buf.as_ptr()), 0, KEY_READ, &mut subkey).is_err() {
                    continue;
                }

                let display_name = read_reg_string(subkey, "DisplayName");
                if let Some(ref dn) = display_name {
                    let d = PyDict::new(py);
                    d.set_item("name", dn)?;
                    d.set_item("path", read_reg_string(subkey, "InstallLocation").unwrap_or_default())?;
                    d.set_item("exe", read_reg_string(subkey, "DisplayIcon").unwrap_or_default())?;
                    apps.push(d.into());
                }
                let _ = RegCloseKey(subkey);
            }
            let _ = RegCloseKey(hkey);
        }
    }
    Ok(apps)
}

/// Open an application by exe path.
#[pyfunction]
pub fn open_app(exe_path: &str) -> PyResult<()> {
    let wide: Vec<u16> = exe_path.encode_utf16().chain(std::iter::once(0)).collect();
    let open: Vec<u16> = "open".encode_utf16().chain(std::iter::once(0)).collect();
    unsafe {
        let result = ShellExecuteW(None, PCWSTR(open.as_ptr()), PCWSTR(wide.as_ptr()), PCWSTR::null(), PCWSTR::null(), SW_SHOWNORMAL);
        if result.0 as usize <= 32 {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
                "ShellExecute failed with code {}",
                result.0 as usize
            )));
        }
    }
    Ok(())
}

/// Get the app under a screen coordinate: {exe, title, pid} or None.
#[pyfunction]
pub fn app_under_point(x: i32, y: i32, py: Python<'_>) -> PyResult<Option<PyObject>> {
    unsafe {
        let pt = POINT { x, y };
        let hwnd = WindowFromPoint(pt);
        if hwnd.0 == std::ptr::null_mut() {
            return Ok(None);
        }
        let mut pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));

        let d = PyDict::new(py);
        d.set_item("pid", pid)?;
        d.set_item("title", get_window_title(hwnd))?;
        d.set_item("exe", get_process_exe(pid).unwrap_or_default())?;
        Ok(Some(d.into()))
    }
}

// ---------------------------------------------------------------------------
// Window management — hide/show/activate for prepareForAction
// ---------------------------------------------------------------------------

unsafe extern "system" fn enum_windows_cb(hwnd: HWND, lparam: LPARAM) -> BOOL {
    let results = &mut *(lparam.0 as *mut Vec<(HWND, String)>);
    if IsWindowVisible(hwnd).as_bool() {
        let title = get_window_title(hwnd);
        if !title.is_empty() {
            results.push((hwnd, title));
        }
    }
    BOOL(1)
}

/// Find all visible top-level windows whose title contains `pattern` (case-insensitive).
/// Returns list of (hwnd_as_isize, title).
#[pyfunction]
pub fn find_windows_by_title(pattern: &str, py: Python<'_>) -> PyResult<Vec<PyObject>> {
    let pattern_lower = pattern.to_lowercase();
    let mut all_windows: Vec<(HWND, String)> = Vec::new();
    unsafe {
        let _ = EnumWindows(
            Some(enum_windows_cb),
            LPARAM(&mut all_windows as *mut Vec<(HWND, String)> as isize),
        );
    }
    let mut result = Vec::new();
    for (hwnd, title) in all_windows {
        if title.to_lowercase().contains(&pattern_lower) {
            let d = PyDict::new(py);
            d.set_item("hwnd", hwnd.0 as isize)?;
            d.set_item("title", &title)?;
            result.push(d.into());
        }
    }
    Ok(result)
}

/// Hide a window (SW_HIDE — instant, no animation).
#[pyfunction]
pub fn hide_window(hwnd: isize) -> PyResult<()> {
    unsafe {
        let _ = ShowWindow(HWND(hwnd as *mut _), SW_HIDE);
    }
    Ok(())
}

/// Show a previously hidden window (SW_SHOW).
#[pyfunction]
pub fn show_window(hwnd: isize) -> PyResult<()> {
    unsafe {
        let _ = ShowWindow(HWND(hwnd as *mut _), SW_SHOW);
    }
    Ok(())
}

/// Minimize a window (SW_MINIMIZE).
#[pyfunction]
pub fn minimize_window(hwnd: isize) -> PyResult<()> {
    unsafe {
        let _ = ShowWindow(HWND(hwnd as *mut _), SW_MINIMIZE);
    }
    Ok(())
}

/// Restore a minimized/hidden window (SW_RESTORE).
#[pyfunction]
pub fn restore_window(hwnd: isize) -> PyResult<()> {
    unsafe {
        let _ = ShowWindow(HWND(hwnd as *mut _), SW_RESTORE);
    }
    Ok(())
}

/// Bring a window to the foreground and activate it.
#[pyfunction]
pub fn set_foreground(hwnd: isize) -> PyResult<bool> {
    unsafe {
        let h = HWND(hwnd as *mut _);
        if IsIconic(h).as_bool() {
            let _ = ShowWindow(h, SW_RESTORE);
        }
        Ok(SetForegroundWindow(h).as_bool())
    }
}

/// Mark a window as excluded from screen capture (Windows 10 2004+).
///
/// Uses `SetWindowDisplayAffinity(WDA_EXCLUDEDFROMCAPTURE)`:
///   - The window is still visible on screen to the user.
///   - Any BitBlt / PrintWindow / DWM capture sees *through* it
///     (the desktop behind it is captured instead).
///   - Zero flicker — no hide/show needed.
///
/// Pass `excluded=false` to restore normal capture behaviour.
#[pyfunction]
pub fn set_capture_excluded(hwnd: isize, excluded: bool) -> PyResult<bool> {
    // WDA_EXCLUDEDFROMCAPTURE = 0x11, WDA_NONE = 0x00
    const WDA_EXCLUDEDFROMCAPTURE: u32 = 0x00000011;
    const WDA_NONE: u32 = 0x00000000;
    let affinity = if excluded { WDA_EXCLUDEDFROMCAPTURE } else { WDA_NONE };
    unsafe {
        let h = HWND(hwnd as *mut _);
        Ok(SetWindowDisplayAffinity(h, WINDOW_DISPLAY_AFFINITY(affinity)).is_ok())
    }
}
