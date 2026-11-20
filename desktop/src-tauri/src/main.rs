#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use wifi_core::{generate_qr_png, WifiError, WifiIdentity, WifiProfile};

#[derive(Serialize)]
struct IdentityResponse {
    client_os: String,
    host_os: String,
    os_matches: bool,
    adapter: String,
    current_ssid: Option<String>,
    saved_profile_names: bool,
    credential_reveal: bool,
    limitation: Option<String>,
}

fn os_name(os: wifi_core::DesktopOs) -> &'static str {
    match os {
        wifi_core::DesktopOs::Windows => "windows",
        wifi_core::DesktopOs::Macos => "macos",
        wifi_core::DesktopOs::Linux => "linux",
        wifi_core::DesktopOs::Unsupported => "unknown",
    }
}

fn identity_response(identity: WifiIdentity) -> IdentityResponse {
    let host_os = os_name(identity.client_os).to_owned();
    IdentityResponse {
        client_os: host_os.clone(),
        host_os,
        os_matches: true,
        adapter: identity.adapter,
        current_ssid: identity.current_ssid,
        saved_profile_names: identity.saved_profile_names,
        credential_reveal: identity.credential_reveal,
        limitation: identity.limitation,
    }
}

fn public_error(error: WifiError) -> String {
    error.to_string()
}

#[tauri::command]
async fn wifi_identity() -> Result<IdentityResponse, String> {
    let adapter = wifi_platform::adapter().map_err(public_error)?;
    adapter
        .identity()
        .await
        .map(identity_response)
        .map_err(public_error)
}

#[tauri::command]
async fn wifi_profiles() -> Result<Vec<WifiProfile>, String> {
    let adapter = wifi_platform::adapter().map_err(public_error)?;
    adapter.profiles().await.map_err(public_error)
}

#[tauri::command]
async fn wifi_generate_qr(profile_id: String, confirmed: bool) -> Result<Vec<u8>, String> {
    if !confirmed {
        return Err(WifiError::ConfirmationRequired.to_string());
    }
    let adapter = wifi_platform::adapter().map_err(public_error)?;
    let credentials = adapter
        .reveal_selected(&profile_id)
        .await
        .map_err(public_error)?;
    generate_qr_png(&credentials).map_err(public_error)
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            wifi_identity,
            wifi_profiles,
            wifi_generate_qr
        ])
        .run(tauri::generate_context!())
        .expect("WI-FI分享家 desktop runtime failed");
}
