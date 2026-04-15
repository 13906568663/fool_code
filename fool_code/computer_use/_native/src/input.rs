use enigo::{
    Axis, Button, Coordinate, Direction, Enigo, Keyboard, Mouse, Settings,
};
use pyo3::prelude::*;
use std::thread;
use std::time::Duration;

fn make_enigo() -> Result<Enigo, String> {
    Enigo::new(&Settings::default()).map_err(|e| format!("Enigo init: {e}"))
}

fn map_button(name: &str) -> Result<Button, String> {
    match name {
        "left" => Ok(Button::Left),
        "right" => Ok(Button::Right),
        "middle" => Ok(Button::Middle),
        _ => Err(format!("unknown button: {name}")),
    }
}

/// Move the mouse cursor to absolute (x, y).
#[pyfunction]
pub fn move_mouse(x: i32, y: i32) -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
    e.move_mouse(x, y, Coordinate::Abs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))
}

/// Click at (x, y) with given button and count.
#[pyfunction]
#[pyo3(signature = (x, y, button="left", count=1))]
pub fn click(x: i32, y: i32, button: &str, count: u32) -> PyResult<()> {
    let btn = map_button(button).map_err(pyo3::exceptions::PyValueError::new_err)?;
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;

    e.move_mouse(x, y, Coordinate::Abs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    thread::sleep(Duration::from_millis(50));

    for i in 0..count {
        if i > 0 {
            thread::sleep(Duration::from_millis(8));
        }
        e.button(btn, Direction::Click)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    }
    Ok(())
}

/// Press left mouse button down.
#[pyfunction]
pub fn mouse_down() -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
    e.button(Button::Left, Direction::Press)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))
}

/// Release left mouse button.
#[pyfunction]
pub fn mouse_up() -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
    e.button(Button::Left, Direction::Release)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))
}

/// Scroll at (x, y). dy > 0 = up, dx > 0 = right.
#[pyfunction]
pub fn scroll(x: i32, y: i32, dx: i32, dy: i32) -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;

    e.move_mouse(x, y, Coordinate::Abs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    thread::sleep(Duration::from_millis(50));

    if dy != 0 {
        e.scroll(dy, Axis::Vertical)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    }
    if dx != 0 {
        e.scroll(dx, Axis::Horizontal)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    }
    Ok(())
}

/// Drag from (fx, fy) to (tx, ty). If from is None, drag from current position.
#[pyfunction]
#[pyo3(signature = (to_x, to_y, from_x=None, from_y=None))]
pub fn drag(to_x: i32, to_y: i32, from_x: Option<i32>, from_y: Option<i32>) -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;

    if let (Some(fx), Some(fy)) = (from_x, from_y) {
        e.move_mouse(fx, fy, Coordinate::Abs)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
        thread::sleep(Duration::from_millis(50));
    }

    e.button(Button::Left, Direction::Press)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    thread::sleep(Duration::from_millis(50));

    e.move_mouse(to_x, to_y, Coordinate::Abs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    thread::sleep(Duration::from_millis(50));

    e.button(Button::Left, Direction::Release)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
    Ok(())
}

/// Get the current cursor position as (x, y).
#[pyfunction]
pub fn get_cursor_position() -> PyResult<(i32, i32)> {
    use windows::Win32::UI::WindowsAndMessaging::GetCursorPos;
    let mut pt = windows::Win32::Foundation::POINT::default();
    unsafe {
        GetCursorPos(&mut pt)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("GetCursorPos: {e}")))?;
    }
    Ok((pt.x, pt.y))
}

/// Press a key sequence like "ctrl+shift+a". Supports repeat.
#[pyfunction]
#[pyo3(signature = (key_sequence, repeat=1))]
pub fn key(key_sequence: &str, repeat: u32) -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;

    let parts: Vec<&str> = key_sequence.split('+').filter(|s| !s.is_empty()).collect();

    for i in 0..repeat {
        if i > 0 {
            thread::sleep(Duration::from_millis(8));
        }

        // Press modifiers
        for &p in &parts[..parts.len().saturating_sub(1)] {
            if let Some(k) = parse_key(p) {
                e.key(k, Direction::Press)
                    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
            }
        }

        // Click the final key
        if let Some(last) = parts.last() {
            if let Some(k) = parse_key(last) {
                e.key(k, Direction::Click)
                    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
            }
        }

        // Release modifiers in reverse
        for &p in parts[..parts.len().saturating_sub(1)].iter().rev() {
            if let Some(k) = parse_key(p) {
                e.key(k, Direction::Release)
                    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
            }
        }
    }
    Ok(())
}

/// Type text string.
#[pyfunction]
pub fn type_text(text: &str) -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
    e.text(text)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))
}

/// Hold keys for a duration in milliseconds.
#[pyfunction]
pub fn hold_key(keys: Vec<String>, duration_ms: u64) -> PyResult<()> {
    let mut e = make_enigo().map_err(pyo3::exceptions::PyRuntimeError::new_err)?;

    let mut pressed = Vec::new();
    for name in &keys {
        if let Some(k) = parse_key(name) {
            e.key(k, Direction::Press)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{e}")))?;
            pressed.push(k);
        }
    }

    thread::sleep(Duration::from_millis(duration_ms));

    for k in pressed.into_iter().rev() {
        let _ = e.key(k, Direction::Release);
    }
    Ok(())
}

fn parse_key(name: &str) -> Option<enigo::Key> {
    match name.to_lowercase().as_str() {
        "ctrl" | "control" => Some(enigo::Key::Control),
        "alt" => Some(enigo::Key::Alt),
        "shift" => Some(enigo::Key::Shift),
        "meta" | "win" | "command" | "super" => Some(enigo::Key::Meta),
        "enter" | "return" => Some(enigo::Key::Return),
        "tab" => Some(enigo::Key::Tab),
        "space" => Some(enigo::Key::Space),
        "backspace" => Some(enigo::Key::Backspace),
        "delete" => Some(enigo::Key::Delete),
        "escape" | "esc" => Some(enigo::Key::Escape),
        "up" => Some(enigo::Key::UpArrow),
        "down" => Some(enigo::Key::DownArrow),
        "left" => Some(enigo::Key::LeftArrow),
        "right" => Some(enigo::Key::RightArrow),
        "home" => Some(enigo::Key::Home),
        "end" => Some(enigo::Key::End),
        "pageup" => Some(enigo::Key::PageUp),
        "pagedown" => Some(enigo::Key::PageDown),
        "f1" => Some(enigo::Key::F1),
        "f2" => Some(enigo::Key::F2),
        "f3" => Some(enigo::Key::F3),
        "f4" => Some(enigo::Key::F4),
        "f5" => Some(enigo::Key::F5),
        "f6" => Some(enigo::Key::F6),
        "f7" => Some(enigo::Key::F7),
        "f8" => Some(enigo::Key::F8),
        "f9" => Some(enigo::Key::F9),
        "f10" => Some(enigo::Key::F10),
        "f11" => Some(enigo::Key::F11),
        "f12" => Some(enigo::Key::F12),
        "capslock" => Some(enigo::Key::CapsLock),
        s if s.len() == 1 => Some(enigo::Key::Unicode(s.chars().next().unwrap())),
        _ => None,
    }
}
