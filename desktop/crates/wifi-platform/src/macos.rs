use async_trait::async_trait;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use corewlan::prelude::*;
use wifi_core::{
    DesktopOs, WifiAdapter, WifiCredentials, WifiError, WifiIdentity, WifiProfile, WifiSecurity,
};
use zeroize::Zeroizing;

pub struct MacWifiAdapter;

fn client() -> Result<WiFiClient, WifiError> {
    WiFiClient::shared().map_err(|_| WifiError::OsService("CoreWLAN is unavailable.".into()))
}

fn all_profiles() -> Result<Vec<NetworkProfile>, WifiError> {
    let client = client()?;
    Ok(client
        .interface()
        .and_then(|interface| interface.configuration())
        .map(|configuration| configuration.network_profiles())
        .unwrap_or_default())
}

fn profile_id(profile: &NetworkProfile) -> Option<String> {
    let ssid = profile.ssid_data()?;
    let security = profile.security().as_raw().to_le_bytes();
    let mut opaque = Vec::with_capacity(security.len() + ssid.len());
    opaque.extend_from_slice(&security);
    opaque.extend_from_slice(&ssid);
    Some(URL_SAFE_NO_PAD.encode(opaque))
}

fn decode_profile_id(id: &str) -> Result<(isize, Vec<u8>), WifiError> {
    let opaque = URL_SAFE_NO_PAD
        .decode(id)
        .map_err(|_| WifiError::ProfileNotFound)?;
    let (security, ssid) = opaque
        .split_at_checked(std::mem::size_of::<isize>())
        .ok_or(WifiError::ProfileNotFound)?;
    if ssid.is_empty() {
        return Err(WifiError::ProfileNotFound);
    }
    let security: [u8; std::mem::size_of::<isize>()] = security
        .try_into()
        .map_err(|_| WifiError::ProfileNotFound)?;
    Ok((isize::from_le_bytes(security), ssid.to_vec()))
}

#[async_trait]
impl WifiAdapter for MacWifiAdapter {
    async fn identity(&self) -> Result<WifiIdentity, WifiError> {
        let client = client()?;
        let interface = client.interface();
        let (current_ssid, limitation) = match interface.as_ref().map(Interface::ssid) {
            Some(Ok(ssid)) => (ssid, None),
            Some(Err(_)) => (
                None,
                Some("macOS 可能需要允許此 App 使用定位服務才能提供目前 SSID。".into()),
            ),
            None => (None, None),
        };
        Ok(WifiIdentity {
            client_os: DesktopOs::Macos,
            adapter: "Apple CoreWLAN + Keychain".into(),
            current_ssid,
            saved_profile_names: true,
            credential_reveal: true,
            limitation,
        })
    }

    async fn profiles(&self) -> Result<Vec<WifiProfile>, WifiError> {
        let profiles = all_profiles()?;
        let current = client()
            .ok()
            .and_then(|client| client.interface())
            .and_then(|interface| interface.ssid().ok().flatten());
        Ok(profiles
            .iter()
            .filter_map(|profile| {
                let id = profile_id(profile)?;
                let name = profile.ssid()?;
                Some(WifiProfile {
                    is_current: current.as_deref() == Some(name.as_str()),
                    id,
                    name,
                })
            })
            .collect())
    }

    async fn reveal_selected(&self, profile_id: &str) -> Result<WifiCredentials, WifiError> {
        let (security_raw, ssid_bytes) = decode_profile_id(profile_id)?;
        let profile = all_profiles()?
            .into_iter()
            .find(|profile| {
                profile.security().as_raw() == security_raw
                    && profile.ssid_data().as_deref() == Some(ssid_bytes.as_slice())
            })
            .ok_or(WifiError::ProfileNotFound)?;
        let ssid = profile.ssid().ok_or(WifiError::ProfileNotFound)?;
        let security = match profile.security() {
            Security::None => WifiSecurity::Open,
            Security::Wep => WifiSecurity::Wep,
            Security::WpaPersonal
            | Security::WpaPersonalMixed
            | Security::Wpa2Personal
            | Security::Personal
            | Security::Wpa3Personal
            | Security::Wpa3Transition => WifiSecurity::Wpa,
            Security::WpaEnterprise
            | Security::WpaEnterpriseMixed
            | Security::Wpa2Enterprise
            | Security::Enterprise
            | Security::Wpa3Enterprise
            | Security::DynamicWep => return Err(WifiError::EnterpriseNetwork),
            Security::Owe | Security::OweTransition | Security::Unknown(_) => {
                return Err(WifiError::UnsupportedSecurity)
            }
            _ => return Err(WifiError::UnsupportedSecurity),
        };
        let password = if security == WifiSecurity::Open {
            Zeroizing::new(String::new())
        } else {
            let secret = find_wifi_password(KeychainDomain::User, &ssid_bytes)
                .map_err(|_| WifiError::AccessDenied)?
                .or_else(|| {
                    find_wifi_password(KeychainDomain::System, &ssid_bytes)
                        .ok()
                        .flatten()
                })
                .ok_or(WifiError::AccessDenied)?;
            Zeroizing::new(secret.expose().to_owned())
        };
        Ok(WifiCredentials::from_secret(
            ssid, password, security, false,
        ))
    }
}
