import Capacitor
import CoreLocation
import NetworkExtension

@objc(NativeWifiBridgePlugin)
public class NativeWifiBridgePlugin: CAPPlugin, CAPBridgedPlugin, CLLocationManagerDelegate {
    public let identifier = "NativeWifiBridgePlugin"
    public let jsName = "NativeWifiBridge"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getCurrentConnection", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openSystemWifiShare", returnType: CAPPluginReturnPromise)
    ]

    private var locationManager: CLLocationManager?
    private var pendingCall: CAPPluginCall?

    @objc func getCurrentConnection(_ call: CAPPluginCall) {
        guard #available(iOS 14.0, *) else {
            call.reject("讀取目前 Wi-Fi 名稱需要 iOS 14 或更新版本。")
            return
        }

        let status = CLLocationManager.authorizationStatus()
        if status == .authorizedWhenInUse || status == .authorizedAlways {
            fetchCurrentNetwork(call)
            return
        }
        if status == .notDetermined {
            pendingCall = call
            locationManager = CLLocationManager()
            locationManager?.delegate = self
            locationManager?.requestWhenInUseAuthorization()
            return
        }
        call.reject("需要允許此 App 使用位置資訊，OS 才能提供目前 Wi-Fi 名稱。也請確認已啟用精確位置與 Access Wi-Fi Information entitlement。")
    }

    public func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard let call = pendingCall else { return }
        let status = manager.authorizationStatus
        if status == .authorizedWhenInUse || status == .authorizedAlways {
            pendingCall = nil
            fetchCurrentNetwork(call)
        } else if status == .denied || status == .restricted {
            pendingCall = nil
            call.reject("位置權限未授權；OS 未提供目前 Wi-Fi 名稱。")
        }
    }

    @available(iOS 14.0, *)
    private func fetchCurrentNetwork(_ call: CAPPluginCall) {
        let manager = locationManager ?? CLLocationManager()
        locationManager = manager
        guard manager.accuracyAuthorization == .fullAccuracy else {
            manager.requestTemporaryFullAccuracyAuthorization(
                withPurposeKey: "WiFiConnectionInfo"
            ) { [weak self] error in
                guard error == nil, manager.accuracyAuthorization == .fullAccuracy else {
                    call.reject("需要精確位置授權，iOS 才能提供目前 Wi-Fi 名稱。")
                    return
                }
                self?.readCurrentNetwork(call)
            }
            return
        }
        readCurrentNetwork(call)
    }

    @available(iOS 14.0, *)
    private func readCurrentNetwork(_ call: CAPPluginCall) {
        NEHotspotNetwork.fetchCurrent { network in
            guard let network else {
                call.reject("OS 沒有回傳目前 Wi-Fi 資訊。請確認 Access Wi-Fi Information entitlement 與授權條件。")
                return
            }
            call.resolve([
                "connected": true,
                "ssid": network.ssid,
                "securityType": String(describing: network.securityType)
            ])
        }
    }

    @objc func openSystemWifiShare(_ call: CAPPluginCall) {
        call.resolve([
            "opened": false,
            "message": "iOS 不提供第三方 App 讀取已存 Wi-Fi 密碼的通用 API。請在「密碼」App 的 Wi-Fi 分類或「設定 > Wi-Fi」使用 iOS 的檢視／分享功能。"
        ])
    }
}
