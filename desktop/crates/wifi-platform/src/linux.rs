use std::collections::HashMap;

use async_trait::async_trait;
use nmrs::{
    models::Property,
    raw::{zbus::Proxy, zvariant::OwnedValue},
    NetworkManager, SettingsSummary, WifiKeyMgmt,
};
use wifi_core::{
    DesktopOs, WifiAdapter, WifiCredentials, WifiError, WifiIdentity, WifiProfile, WifiSecurity,
};
use zeroize::Zeroizing;

pub struct LinuxWifiAdapter;

fn manager_error() -> WifiError {
    WifiError::OsService(
        "NetworkManager is unavailable. Ubuntu, Fedora, and Debian builds require the desktop to use NetworkManager.".into(),
    )
}

async fn manager() -> Result<NetworkManager, WifiError> {
    NetworkManager::new().await.map_err(|_| manager_error())
}

fn wifi_profile(profile: &nmrs::SavedConnection) -> Option<(String, WifiSecurity, bool)> {
    let SettingsSummary::Wifi {
        ssid,
        security,
        hidden,
        ..
    } = &profile.summary
    else {
        return None;
    };
    let security = match security.as_ref().map(|value| value.key_mgmt) {
        None if !profile.has_section("802-11-wireless-security") => WifiSecurity::Open,
        None | Some(WifiKeyMgmt::None | WifiKeyMgmt::Wep) => WifiSecurity::Wep,
        Some(WifiKeyMgmt::WpaPsk | WifiKeyMgmt::Sae) => WifiSecurity::Wpa,
        Some(WifiKeyMgmt::WpaEap) => {
            return Some((ssid.clone(), WifiSecurity::Wpa, *hidden));
        }
        Some(WifiKeyMgmt::Owe | WifiKeyMgmt::OweTransitionMode) => {
            return Some((ssid.clone(), WifiSecurity::Wpa, *hidden));
        }
        Some(_) => return None,
    };
    Some((ssid.clone(), security, *hidden))
}

async fn list_profiles(manager: &NetworkManager) -> Result<Vec<WifiProfile>, WifiError> {
    let current_ssid = manager.current_ssid().await;
    let saved = manager
        .list_saved_connections()
        .await
        .map_err(|_| manager_error())?;
    Ok(saved
        .iter()
        .filter_map(|profile| {
            let (ssid, _, _) = wifi_profile(profile)?;
            Some(WifiProfile {
                id: profile.uuid.clone(),
                is_current: current_ssid.as_deref() == Some(ssid.as_str()),
                name: if ssid.is_empty() {
                    profile.id.clone()
                } else {
                    ssid
                },
            })
        })
        .collect())
}

async fn get_saved_secret(
    manager: &NetworkManager,
    profile: &nmrs::SavedConnection,
    requested_key: &str,
) -> Result<Zeroizing<String>, WifiError> {
    let proxy = Proxy::new(
        manager.dbus_connection(),
        "org.freedesktop.NetworkManager",
        profile.path.as_str(),
        "org.freedesktop.NetworkManager.Settings.Connection",
    )
    .await
    .map_err(|_| WifiError::AccessDenied)?;
    let setting_name = "802-11-wireless-security";
    let mut all: HashMap<String, HashMap<String, OwnedValue>> = proxy
        .call("GetSecrets", &setting_name)
        .await
        .map_err(|_| WifiError::AccessDenied)?;
    let secret = all
        .get_mut(setting_name)
        .and_then(|setting| setting.remove(requested_key))
        .ok_or(WifiError::AccessDenied)?;
    let secret = String::try_from(secret).map_err(|_| WifiError::AccessDenied)?;
    Ok(Zeroizing::new(secret))
}

#[async_trait]
impl WifiAdapter for LinuxWifiAdapter {
    async fn identity(&self) -> Result<WifiIdentity, WifiError> {
        let manager = manager().await?;
        Ok(WifiIdentity {
            client_os: DesktopOs::Linux,
            adapter: "NetworkManager D-Bus".into(),
            current_ssid: manager.current_ssid().await,
            saved_profile_names: true,
            credential_reveal: true,
            limitation: Some(
                "僅支援由 NetworkManager 管理的 Wi-Fi；明文密碼只在 NetworkManager 按目前授權回傳時可用。".into(),
            ),
        })
    }

    async fn profiles(&self) -> Result<Vec<WifiProfile>, WifiError> {
        list_profiles(&manager().await?).await
    }

    async fn reveal_selected(&self, profile_id: &str) -> Result<WifiCredentials, WifiError> {
        let manager = manager().await?;
        let saved = manager
            .list_saved_connections()
            .await
            .map_err(|_| manager_error())?;
        let profile = saved
            .iter()
            .find(|profile| profile.uuid == profile_id)
            .ok_or(WifiError::ProfileNotFound)?;
        let (ssid, security, hidden) = wifi_profile(profile).ok_or(WifiError::ProfileNotFound)?;
        let key_mgmt = match &profile.summary {
            SettingsSummary::Wifi { security, .. } => security.as_ref().map(|s| s.key_mgmt),
            _ => None,
        };
        if key_mgmt == Some(WifiKeyMgmt::WpaEap) {
            return Err(WifiError::EnterpriseNetwork);
        }
        if matches!(
            key_mgmt,
            Some(WifiKeyMgmt::Owe | WifiKeyMgmt::OweTransitionMode)
        ) {
            return Err(WifiError::UnsupportedSecurity);
        }
        let password = match security {
            WifiSecurity::Open => Zeroizing::new(String::new()),
            WifiSecurity::Wep => {
                let index = profile
                    .get_property(Property::<u32>::new(
                        "802-11-wireless-security",
                        "wep-tx-keyidx",
                    ))
                    .unwrap_or(0);
                if index > 3 {
                    return Err(WifiError::UnsupportedSecurity);
                }
                get_saved_secret(&manager, profile, &format!("wep-key{index}")).await?
            }
            WifiSecurity::Wpa => get_saved_secret(&manager, profile, "psk").await?,
        };
        Ok(WifiCredentials::from_secret(
            ssid, password, security, hidden,
        ))
    }
}
