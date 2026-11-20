use std::{
    ffi::c_void,
    mem::{offset_of, size_of},
    ptr::{null, null_mut},
};

use async_trait::async_trait;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use wifi_core::{
    DesktopOs, WifiAdapter, WifiCredentials, WifiError, WifiIdentity, WifiProfile, WifiSecurity,
};
use windows_sys::{
    core::GUID,
    Win32::{
        Foundation::HANDLE,
        NetworkManagement::WiFi::{
            wlan_interface_state_connected, wlan_intf_opcode_current_connection, WlanCloseHandle,
            WlanEnumInterfaces, WlanFreeMemory, WlanGetProfile, WlanGetProfileList, WlanOpenHandle,
            WlanQueryInterface, WLAN_CONNECTION_ATTRIBUTES, WLAN_INTERFACE_INFO,
            WLAN_INTERFACE_INFO_LIST, WLAN_PROFILE_GET_PLAINTEXT_KEY, WLAN_PROFILE_INFO,
            WLAN_PROFILE_INFO_LIST,
        },
        UI::Shell::IsUserAnAdmin,
    },
};
use zeroize::Zeroizing;

const ACCESS_DENIED: u32 = 5;

pub struct WindowsWifiAdapter;

struct WlanHandle(HANDLE);

impl WlanHandle {
    fn open() -> Result<Self, WifiError> {
        let mut negotiated = 0;
        let mut handle: HANDLE = null_mut();
        let status = unsafe { WlanOpenHandle(2, null(), &mut negotiated, &mut handle) };
        if status != 0 {
            return Err(WifiError::OsService(format!("Native Wi-Fi error {status}")));
        }
        Ok(Self(handle))
    }
}

impl Drop for WlanHandle {
    fn drop(&mut self) {
        unsafe { WlanCloseHandle(self.0, null()) };
    }
}

struct WlanMemory(*mut c_void);

impl Drop for WlanMemory {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { WlanFreeMemory(self.0) };
        }
    }
}

fn utf16(value: &[u16]) -> String {
    let end = value
        .iter()
        .position(|unit| *unit == 0)
        .unwrap_or(value.len());
    String::from_utf16_lossy(&value[..end])
}

fn interfaces(handle: HANDLE) -> Result<Vec<WLAN_INTERFACE_INFO>, WifiError> {
    let mut pointer = null_mut();
    let status = unsafe { WlanEnumInterfaces(handle, null(), &mut pointer) };
    if status != 0 {
        return Err(WifiError::OsService(format!("Native Wi-Fi error {status}")));
    }
    let _memory = WlanMemory(pointer.cast());
    if pointer.is_null() {
        return Ok(Vec::new());
    }
    let list = unsafe { &*pointer };
    let count = list.dwNumberOfItems as usize;
    let start = pointer.cast::<u8>();
    let first = offset_of!(WLAN_INTERFACE_INFO_LIST, InterfaceInfo);
    (0..count)
        .map(|index| {
            let item = unsafe {
                &*(start
                    .add(first + index * size_of::<WLAN_INTERFACE_INFO>())
                    .cast::<WLAN_INTERFACE_INFO>())
            };
            Ok(unsafe { std::ptr::read(item) })
        })
        .collect()
}

fn interface_id(guid: &GUID) -> String {
    // GUID's C layout is stable and its fields are public in windows-sys.
    format!(
        "{:08x}-{:04x}-{:04x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
        guid.data1,
        guid.data2,
        guid.data3,
        guid.data4[0],
        guid.data4[1],
        guid.data4[2],
        guid.data4[3],
        guid.data4[4],
        guid.data4[5],
        guid.data4[6],
        guid.data4[7]
    )
}

fn current_connection(handle: HANDLE) -> Option<(String, String)> {
    for interface in interfaces(handle).ok()? {
        let mut size = 0;
        let mut data = null_mut();
        let status = unsafe {
            WlanQueryInterface(
                handle,
                &interface.InterfaceGuid,
                wlan_intf_opcode_current_connection,
                null(),
                &mut size,
                &mut data,
                null_mut(),
            )
        };
        if status != 0 || data.is_null() {
            continue;
        }
        let _memory = WlanMemory(data);
        let connection = unsafe { &*data.cast::<WLAN_CONNECTION_ATTRIBUTES>() };
        if connection.isState == wlan_interface_state_connected {
            let ssid = &connection.wlanAssociationAttributes.dot11Ssid;
            let length = (ssid.uSSIDLength as usize).min(ssid.ucSSID.len());
            return Some((
                utf16(&connection.strProfileName),
                String::from_utf8_lossy(&ssid.ucSSID[..length]).into_owned(),
            ));
        }
    }
    None
}

fn current_profile(handle: HANDLE) -> Option<String> {
    current_connection(handle).map(|(profile, _)| profile)
}

fn current_ssid(handle: HANDLE) -> Option<String> {
    current_connection(handle).map(|(_, ssid)| ssid)
}

fn list_profiles(handle: HANDLE) -> Result<Vec<WifiProfile>, WifiError> {
    let current = current_profile(handle);
    let mut result = Vec::new();
    for interface in interfaces(handle)? {
        let mut pointer = null_mut();
        let status =
            unsafe { WlanGetProfileList(handle, &interface.InterfaceGuid, null(), &mut pointer) };
        if status != 0 {
            continue;
        }
        let _memory = WlanMemory(pointer.cast());
        if pointer.is_null() {
            continue;
        }
        let list = unsafe { &*pointer };
        let start = pointer.cast::<u8>();
        let first = offset_of!(WLAN_PROFILE_INFO_LIST, ProfileInfo);
        for index in 0..list.dwNumberOfItems as usize {
            let item = unsafe {
                &*(start
                    .add(first + index * size_of::<WLAN_PROFILE_INFO>())
                    .cast::<WLAN_PROFILE_INFO>())
            };
            let name = utf16(&item.strProfileName);
            let id = URL_SAFE_NO_PAD.encode(format!(
                "{}\0{}",
                interface_id(&interface.InterfaceGuid),
                name
            ));
            result.push(WifiProfile {
                is_current: current.as_deref() == Some(name.as_str()),
                id,
                name,
            });
        }
    }
    Ok(result)
}

fn profile_text<'document, 'xml>(
    document: &'document roxmltree::Document<'xml>,
    name: &str,
) -> &'xml str {
    document
        .descendants()
        .find(|node| node.is_element() && node.tag_name().name() == name)
        .and_then(|node| node.text())
        .unwrap_or("")
}

fn profile_security(
    authentication: &str,
    encryption: &str,
    use_one_x: bool,
    password: &str,
) -> Result<WifiSecurity, WifiError> {
    let authentication = authentication.to_ascii_uppercase();
    let encryption = encryption.to_ascii_uppercase();
    if use_one_x || authentication.contains("8021X") || authentication.contains("EAP") {
        return Err(WifiError::EnterpriseNetwork);
    }
    if encryption == "WEP" {
        return Ok(WifiSecurity::Wep);
    }
    if authentication == "OPEN" && encryption == "NONE" && password.is_empty() {
        return Ok(WifiSecurity::Open);
    }
    if authentication.contains("PSK") || authentication.contains("SAE") {
        return Ok(WifiSecurity::Wpa);
    }
    Err(WifiError::UnsupportedSecurity)
}

fn parse_credentials(xml: &str) -> Result<WifiCredentials, WifiError> {
    let document = roxmltree::Document::parse(xml).map_err(|_| {
        WifiError::OsService("Windows returned an unreadable Wi-Fi profile.".into())
    })?;
    let ssid = document
        .descendants()
        .find(|node| node.is_element() && node.tag_name().name() == "SSID")
        .and_then(|node| {
            node.children()
                .find(|child| child.is_element() && child.tag_name().name() == "name")
        })
        .and_then(|node| node.text())
        .or_else(|| {
            document
                .descendants()
                .find(|node| node.is_element() && node.tag_name().name() == "WLANProfile")
                .and_then(|node| {
                    node.children()
                        .find(|child| child.is_element() && child.tag_name().name() == "name")
                })
                .and_then(|node| node.text())
        })
        .unwrap_or("")
        .to_owned();
    let authentication = profile_text(&document, "authentication");
    let encryption = profile_text(&document, "encryption");
    let use_one_x = profile_text(&document, "useOneX").eq_ignore_ascii_case("true");
    let security = profile_security(authentication, encryption, use_one_x, "")?;
    let key_material = profile_text(&document, "keyMaterial");
    if security == WifiSecurity::Open && !key_material.is_empty() {
        return Err(WifiError::UnsupportedSecurity);
    }
    let password = if security == WifiSecurity::Open {
        String::new()
    } else {
        key_material.to_owned()
    };
    if ssid.is_empty() {
        return Err(WifiError::ProfileNotFound);
    }
    let hidden = profile_text(&document, "nonBroadcast").eq_ignore_ascii_case("true");
    Ok(WifiCredentials::new(ssid, password, security, hidden))
}

fn get_profile_xml(
    handle: HANDLE,
    interface: &GUID,
    profile_name: &str,
    plaintext: bool,
) -> Result<Zeroizing<String>, WifiError> {
    let profile_name: Vec<u16> = profile_name.encode_utf16().chain(Some(0)).collect();
    let mut xml_pointer = null_mut();
    let mut flags = if plaintext {
        WLAN_PROFILE_GET_PLAINTEXT_KEY
    } else {
        0
    };
    let mut access = 0;
    let status = unsafe {
        WlanGetProfile(
            handle,
            interface,
            profile_name.as_ptr(),
            null(),
            &mut xml_pointer,
            &mut flags,
            &mut access,
        )
    };
    if status == ACCESS_DENIED {
        return Err(WifiError::AccessDenied);
    }
    if status != 0 || xml_pointer.is_null() {
        return Err(WifiError::ProfileNotFound);
    }
    let _memory = WlanMemory(xml_pointer.cast());
    let xml = unsafe {
        let mut length = 0;
        while *xml_pointer.add(length) != 0 {
            length += 1;
        }
        String::from_utf16_lossy(std::slice::from_raw_parts(xml_pointer, length))
    };
    Ok(Zeroizing::new(xml))
}

#[async_trait]
impl WifiAdapter for WindowsWifiAdapter {
    async fn identity(&self) -> Result<WifiIdentity, WifiError> {
        let handle = WlanHandle::open()?;
        Ok(WifiIdentity {
            client_os: DesktopOs::Windows,
            adapter: "Windows Native Wi-Fi (wlanapi.dll)".into(),
            current_ssid: current_ssid(handle.0),
            saved_profile_names: true,
            credential_reveal: true,
            limitation: Some("密碼讀取受 Windows WLAN 權限控制；此 App 不會自動提權。".into()),
        })
    }

    async fn profiles(&self) -> Result<Vec<WifiProfile>, WifiError> {
        list_profiles(WlanHandle::open()?.0)
    }

    async fn reveal_selected(&self, profile_id: &str) -> Result<WifiCredentials, WifiError> {
        let decoded = URL_SAFE_NO_PAD
            .decode(profile_id)
            .map_err(|_| WifiError::ProfileNotFound)?;
        let (target_interface, profile_name) = String::from_utf8(decoded)
            .map_err(|_| WifiError::ProfileNotFound)?
            .split_once('\0')
            .map(|(interface, name)| (interface.to_owned(), name.to_owned()))
            .ok_or(WifiError::ProfileNotFound)?;
        let handle = WlanHandle::open()?;
        let interface = interfaces(handle.0)?
            .into_iter()
            .find(|item| interface_id(&item.InterfaceGuid) == target_interface)
            .ok_or(WifiError::ProfileNotFound)?;
        let metadata_xml =
            get_profile_xml(handle.0, &interface.InterfaceGuid, &profile_name, false)?;
        let metadata = roxmltree::Document::parse(metadata_xml.as_str())
            .map_err(|_| WifiError::ProfileNotFound)?;
        let security = profile_security(
            profile_text(&metadata, "authentication"),
            profile_text(&metadata, "encryption"),
            profile_text(&metadata, "useOneX").eq_ignore_ascii_case("true"),
            "",
        )?;
        if security == WifiSecurity::Open {
            return parse_credentials(metadata_xml.as_str());
        }
        if unsafe { IsUserAnAdmin() } == 0 {
            return Err(WifiError::AccessDenied);
        }
        let xml = get_profile_xml(handle.0, &interface.InterfaceGuid, &profile_name, true)?;
        parse_credentials(xml.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secured_personal_profile_is_parsed_without_admin_metadata_leaks() {
        let xml = r#"<WLANProfile>
          <name>Example</name>
          <SSIDConfig><SSID><name>Example</name></SSID><nonBroadcast>true</nonBroadcast></SSIDConfig>
          <MSM><security><authEncryption><authentication>WPA2PSK</authentication>
            <encryption>AES</encryption></authEncryption>
            <sharedKey><keyMaterial>correct-horse</keyMaterial></sharedKey></security></MSM>
        </WLANProfile>"#;
        let credentials = parse_credentials(xml).expect("personal network should be shareable");
        assert_eq!(credentials.ssid, "Example");
        assert_eq!(credentials.password.as_str(), "correct-horse");
        assert!(credentials.hidden);
        assert_eq!(credentials.security, WifiSecurity::Wpa);
    }

    #[test]
    fn enterprise_profile_is_rejected_before_plaintext_key_read() {
        assert!(matches!(
            profile_security("WPA2", "AES", true, ""),
            Err(WifiError::EnterpriseNetwork)
        ));
    }

    #[test]
    fn unknown_security_is_not_guessed_as_wpa() {
        assert!(matches!(
            profile_security("WPA2", "AES", false, ""),
            Err(WifiError::UnsupportedSecurity)
        ));
    }
}
