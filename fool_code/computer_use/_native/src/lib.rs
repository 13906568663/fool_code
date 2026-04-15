use pyo3::prelude::*;

mod apps;
mod clipboard;
mod display;
mod input;
mod screen;

#[pymodule]
fn fool_code_cu(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Screenshot
    m.add_function(wrap_pyfunction!(screen::screenshot, m)?)?;
    m.add_function(wrap_pyfunction!(screen::screenshot_region, m)?)?;
    // Display
    m.add_function(wrap_pyfunction!(display::get_display_size, m)?)?;
    m.add_function(wrap_pyfunction!(display::list_displays, m)?)?;
    // Mouse
    m.add_function(wrap_pyfunction!(input::move_mouse, m)?)?;
    m.add_function(wrap_pyfunction!(input::click, m)?)?;
    m.add_function(wrap_pyfunction!(input::mouse_down, m)?)?;
    m.add_function(wrap_pyfunction!(input::mouse_up, m)?)?;
    m.add_function(wrap_pyfunction!(input::scroll, m)?)?;
    m.add_function(wrap_pyfunction!(input::drag, m)?)?;
    m.add_function(wrap_pyfunction!(input::get_cursor_position, m)?)?;
    // Keyboard
    m.add_function(wrap_pyfunction!(input::key, m)?)?;
    m.add_function(wrap_pyfunction!(input::type_text, m)?)?;
    m.add_function(wrap_pyfunction!(input::hold_key, m)?)?;
    // Clipboard
    m.add_function(wrap_pyfunction!(clipboard::read_clipboard, m)?)?;
    m.add_function(wrap_pyfunction!(clipboard::write_clipboard, m)?)?;
    // Apps
    m.add_function(wrap_pyfunction!(apps::get_foreground_app, m)?)?;
    m.add_function(wrap_pyfunction!(apps::list_running_apps, m)?)?;
    m.add_function(wrap_pyfunction!(apps::list_installed_apps, m)?)?;
    m.add_function(wrap_pyfunction!(apps::open_app, m)?)?;
    m.add_function(wrap_pyfunction!(apps::app_under_point, m)?)?;
    // Window management
    m.add_function(wrap_pyfunction!(apps::find_windows_by_title, m)?)?;
    m.add_function(wrap_pyfunction!(apps::hide_window, m)?)?;
    m.add_function(wrap_pyfunction!(apps::show_window, m)?)?;
    m.add_function(wrap_pyfunction!(apps::minimize_window, m)?)?;
    m.add_function(wrap_pyfunction!(apps::restore_window, m)?)?;
    m.add_function(wrap_pyfunction!(apps::set_foreground, m)?)?;
    m.add_function(wrap_pyfunction!(apps::set_capture_excluded, m)?)?;
    Ok(())
}
