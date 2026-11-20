package com.popuchoco.wifisharing.nativewifi

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.core.content.ContextCompat
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback

@CapacitorPlugin(
    name = "NativeWifiBridge",
    permissions = [
        Permission(
            alias = "nearbyWifi",
            strings = [Manifest.permission.NEARBY_WIFI_DEVICES]
        ),
        Permission(
            alias = "location",
            strings = [Manifest.permission.ACCESS_FINE_LOCATION]
        )
    ]
)
class NativeWifiBridgePlugin : Plugin() {

    @PluginMethod
    fun getCurrentConnection(call: PluginCall) {
        val alias = if (Build.VERSION.SDK_INT >= 33) "nearbyWifi" else "location"
        val permission = if (Build.VERSION.SDK_INT >= 33) {
            Manifest.permission.NEARBY_WIFI_DEVICES
        } else {
            Manifest.permission.ACCESS_FINE_LOCATION
        }
        if (ContextCompat.checkSelfPermission(context, permission) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissionForAlias(alias, call, "wifiPermissionResult")
            return
        }
        resolveCurrentConnection(call)
    }

    @PermissionCallback
    private fun wifiPermissionResult(call: PluginCall) {
        val alias = if (Build.VERSION.SDK_INT >= 33) "nearbyWifi" else "location"
        if (getPermissionState(alias) != com.getcapacitor.PermissionState.GRANTED) {
            call.reject("需要 Wi-Fi 附近裝置權限，才能讀取目前連線名稱。")
            return
        }
        resolveCurrentConnection(call)
    }

    private fun resolveCurrentConnection(call: PluginCall) {
        try {
            val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            if (Build.VERSION.SDK_INT < 24) {
                @Suppress("DEPRECATION")
                val legacyWifiInfo = (context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager).connectionInfo
                val legacySsid = legacyWifiInfo?.ssid?.removeSurrounding("\"")
                if (legacySsid.isNullOrBlank() || legacySsid == WifiManager.UNKNOWN_SSID) {
                    call.reject("OS 未提供 SSID。請確認 Wi-Fi 權限與系統定位設定。")
                } else {
                    call.resolve(JSObject().put("connected", true).put("ssid", legacySsid))
                }
                return
            }
            val completed = java.util.concurrent.atomic.AtomicBoolean(false)
            val timeout = Handler(Looper.getMainLooper())
            lateinit var callback: ConnectivityManager.NetworkCallback

            fun finish(result: JSObject) {
                if (completed.compareAndSet(false, true)) {
                    timeout.removeCallbacksAndMessages(null)
                    try {
                        connectivity.unregisterNetworkCallback(callback)
                    } catch (_: IllegalArgumentException) {
                        // The OS may already have unregistered it during teardown.
                    }
                    call.resolve(result)
                }
            }

            fun handleCapabilities(capabilities: NetworkCapabilities) {
                if (!capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                    finish(JSObject().put("connected", false).put("message", "裝置目前未透過 Wi-Fi 連線。"))
                    return
                }
                val wifiInfo = capabilities.transportInfo as? WifiInfo
                val ssid = wifiInfo?.ssid?.removeSurrounding("\"")
                if (ssid.isNullOrBlank() || ssid == WifiManager.UNKNOWN_SSID) {
                    if (completed.compareAndSet(false, true)) {
                        timeout.removeCallbacksAndMessages(null)
                        try {
                            connectivity.unregisterNetworkCallback(callback)
                        } catch (_: IllegalArgumentException) {
                            // The OS may already have unregistered it during teardown.
                        }
                        call.reject("OS 未提供 SSID。請確認 Wi-Fi 權限與系統定位／附近裝置設定。")
                    }
                    return
                }
                val result = JSObject().put("connected", true).put("ssid", ssid)
                if (Build.VERSION.SDK_INT >= 31 && wifiInfo != null) {
                    result.put("securityType", securityName(wifiInfo.currentSecurityType))
                }
                finish(result)
            }

            val capabilitiesCallback = object : ConnectivityManager.NetworkCallback() {
                override fun onCapabilitiesChanged(network: android.net.Network, capabilities: NetworkCapabilities) {
                    handleCapabilities(capabilities)
                }
            }
            callback = if (Build.VERSION.SDK_INT >= 31) {
                object : ConnectivityManager.NetworkCallback(
                    ConnectivityManager.NetworkCallback.FLAG_INCLUDE_LOCATION_INFO
                ) {
                    override fun onCapabilitiesChanged(network: android.net.Network, capabilities: NetworkCapabilities) {
                        handleCapabilities(capabilities)
                    }
                }
            } else {
                capabilitiesCallback
            }

            val wifiRequest = NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .build()
            connectivity.registerNetworkCallback(wifiRequest, callback)
            timeout.postDelayed({
                if (completed.compareAndSet(false, true)) {
                    try {
                        connectivity.unregisterNetworkCallback(callback)
                    } catch (_: IllegalArgumentException) {
                        // The OS may already have unregistered it during teardown.
                    }
                    call.resolve(JSObject().put("connected", false).put("message", "裝置目前未透過 Wi-Fi 連線。"))
                }
            }, 5_000)
        } catch (error: SecurityException) {
            call.reject("Android 拒絕提供 Wi-Fi 資訊，請確認權限後重試。", error)
        } catch (error: Exception) {
            call.reject("讀取目前 Wi-Fi 連線失敗。", error)
        }
    }

    @PluginMethod
    fun openSystemWifiShare(call: PluginCall) {
        try {
            val intent = Intent(Settings.ACTION_WIFI_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            call.resolve(
                JSObject()
                    .put("opened", true)
                    .put("message", "已開啟 Android Wi-Fi 設定。請選擇已儲存的網路，點選「分享」並由 OS 顯示 QR Code。")
            )
        } catch (error: Exception) {
            call.reject("無法開啟 Android Wi-Fi 設定。", error)
        }
    }

    private fun securityName(type: Int): String = when (type) {
        WifiInfo.SECURITY_TYPE_OPEN -> "Open"
        WifiInfo.SECURITY_TYPE_WEP -> "WEP"
        WifiInfo.SECURITY_TYPE_PSK -> "WPA/WPA2-Personal"
        WifiInfo.SECURITY_TYPE_SAE -> "WPA3-Personal"
        WifiInfo.SECURITY_TYPE_EAP -> "WPA/WPA2-Enterprise"
        WifiInfo.SECURITY_TYPE_OWE -> "Enhanced Open"
        else -> "Unknown"
    }
}
