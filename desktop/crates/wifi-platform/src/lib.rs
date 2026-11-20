//! Native desktop adapters. Each platform calls its own OS networking stack;
//! no credential API is called until the user confirms QR generation.

use wifi_core::{WifiAdapter, WifiError};

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "windows")]
mod windows;

pub fn adapter() -> Result<Box<dyn WifiAdapter>, WifiError> {
    #[cfg(target_os = "windows")]
    {
        return Ok(Box::new(windows::WindowsWifiAdapter));
    }
    #[cfg(target_os = "macos")]
    {
        return Ok(Box::new(macos::MacWifiAdapter));
    }
    #[cfg(target_os = "linux")]
    {
        return Ok(Box::new(linux::LinuxWifiAdapter));
    }
    #[allow(unreachable_code)]
    Err(WifiError::UnsupportedPlatform)
}
