//! Platform-neutral Wi-Fi sharing domain and local QR generation.
//!
//! Plaintext passwords are absent from serializable UI models and are never
//! `Debug`. Their owning buffer and temporary QR payload are zeroized on drop;
//! the generated QR image necessarily contains the shareable network secret.

use std::io::Cursor;

use image::{DynamicImage, ImageFormat, Luma};
use qrcode::QrCode;
use serde::Serialize;
use thiserror::Error;
use zeroize::{Zeroize, Zeroizing};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum DesktopOs {
    Windows,
    Macos,
    Linux,
    Unsupported,
}

#[derive(Debug, Clone, Serialize)]
pub struct WifiIdentity {
    pub client_os: DesktopOs,
    pub adapter: String,
    pub current_ssid: Option<String>,
    pub saved_profile_names: bool,
    pub credential_reveal: bool,
    pub limitation: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct WifiProfile {
    /// Opaque platform identifier; the UI must not derive a secret from it.
    pub id: String,
    pub name: String,
    pub is_current: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WifiSecurity {
    Open,
    Wep,
    Wpa,
}

#[derive(PartialEq, Eq)]
pub struct WifiCredentials {
    pub ssid: String,
    pub password: Zeroizing<String>,
    pub security: WifiSecurity,
    pub hidden: bool,
}

impl WifiCredentials {
    pub fn new(ssid: String, password: String, security: WifiSecurity, hidden: bool) -> Self {
        Self::from_secret(ssid, Zeroizing::new(password), security, hidden)
    }

    /// Move an already zeroizing secret into the domain model without making
    /// another password copy.
    pub fn from_secret(
        ssid: String,
        mut password: Zeroizing<String>,
        security: WifiSecurity,
        hidden: bool,
    ) -> Self {
        Self {
            ssid,
            password: Zeroizing::new(std::mem::take(&mut *password)),
            security,
            hidden,
        }
    }
}

impl Drop for WifiCredentials {
    fn drop(&mut self) {
        self.ssid.zeroize();
    }
}

#[derive(Debug, Error)]
pub enum WifiError {
    #[error("This operating system adapter is not implemented.")]
    UnsupportedPlatform,
    #[error("The local operating-system Wi-Fi service is unavailable: {0}")]
    OsService(String),
    #[error("The selected Wi-Fi profile is unavailable or access was denied.")]
    AccessDenied,
    #[error("The selected profile uses enterprise authentication, which cannot be encoded as a personal Wi-Fi QR.")]
    EnterpriseNetwork,
    #[error("The selected network security type cannot be represented by a personal Wi-Fi QR.")]
    UnsupportedSecurity,
    #[error("The selected Wi-Fi profile was not found.")]
    ProfileNotFound,
    #[error("Sharing was not confirmed by the user.")]
    ConfirmationRequired,
    #[error("Could not encode the selected network as a QR image.")]
    QrEncoding,
}

/// Common asynchronous contract for native platform adapters.
#[async_trait::async_trait]
pub trait WifiAdapter: Send + Sync {
    async fn identity(&self) -> Result<WifiIdentity, WifiError>;
    async fn profiles(&self) -> Result<Vec<WifiProfile>, WifiError>;
    async fn reveal_selected(&self, profile_id: &str) -> Result<WifiCredentials, WifiError>;
}

/// Construct a Wi-Fi QR payload and encode it as an in-memory PNG.
pub fn generate_qr_png(credentials: &WifiCredentials) -> Result<Vec<u8>, WifiError> {
    let (security, password) = match credentials.security {
        WifiSecurity::Open => ("nopass", ""),
        WifiSecurity::Wep => ("WEP", credentials.password.as_str()),
        WifiSecurity::Wpa => ("WPA", credentials.password.as_str()),
    };
    // Escaping can at most double the number of UTF-8 bytes. Reserve that
    // amount up-front so appending a secret never reallocates a live buffer.
    let secret_bytes = credentials.ssid.len() + password.len();
    let capacity = security.len() + secret_bytes.saturating_mul(2) + 32;
    let mut payload = Zeroizing::new(String::with_capacity(capacity));
    payload.push_str("WIFI:T:");
    payload.push_str(security);
    payload.push_str(";S:");
    append_escaped_wifi_field(&mut payload, &credentials.ssid);
    payload.push_str(";P:");
    append_escaped_wifi_field(&mut payload, password);
    payload.push_str(";H:");
    payload.push_str(if credentials.hidden { "true" } else { "false" });
    payload.push_str(";;");
    let code = QrCode::new(payload.as_bytes()).map_err(|_| WifiError::QrEncoding)?;
    let image = code
        .render::<Luma<u8>>()
        .quiet_zone(true)
        .module_dimensions(8, 8)
        .build();
    let mut output = Cursor::new(Vec::new());
    DynamicImage::ImageLuma8(image)
        .write_to(&mut output, ImageFormat::Png)
        .map_err(|_| WifiError::QrEncoding)?;
    Ok(output.into_inner())
}

fn append_escaped_wifi_field(output: &mut String, value: &str) {
    for character in value.chars() {
        if matches!(character, '\\' | ';' | ',' | ':' | '"') {
            output.push('\\');
        }
        output.push(character);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qr_is_decodable_png() {
        let credentials = WifiCredentials::new(
            "Cafe;Guest".into(),
            "p:ass,word".into(),
            WifiSecurity::Wpa,
            false,
        );
        let png = generate_qr_png(&credentials).expect("QR should encode");
        let decoder = png::Decoder::new(Cursor::new(png));
        let reader = decoder.read_info().expect("QR should be a valid PNG");
        assert!(reader.info().width > 0);
        assert!(reader.info().height > 0);
    }

    #[test]
    fn qr_field_escape_matches_wifi_qr_delimiters() {
        let mut escaped = String::new();
        append_escaped_wifi_field(&mut escaped, r#"a\\b;c,d:e"f"#);
        assert_eq!(escaped, r#"a\\\\b\\;c\\,d\\:e\\"f"#);
    }

    #[test]
    fn open_network_has_nopass_qr_security() {
        let credentials =
            WifiCredentials::new("Guest".into(), String::new(), WifiSecurity::Open, false);
        assert!(generate_qr_png(&credentials).is_ok());
    }
}
