import { Capacitor } from "@capacitor/core";
import { NativeWifiBridge } from "native-wifi-bridge";
import "./styles.css";

const platform = Capacitor.getPlatform();
const platformNames: Record<string, string> = {
  android: "Android",
  ios: "iOS",
  web: "瀏覽器（未提供 OS 系統 API）",
};

const title = document.querySelector<HTMLHeadingElement>("#deviceTitle")!;
const status = document.querySelector<HTMLDivElement>("#deviceStatus")!;
const networkTitle = document.querySelector<HTMLHeadingElement>("#networkTitle")!;
const networkMeta = document.querySelector<HTMLParagraphElement>("#networkMeta")!;
const readButton = document.querySelector<HTMLButtonElement>("#readCurrentWifi")!;
const shareButton = document.querySelector<HTMLButtonElement>("#shareSystemWifi")!;

title.textContent = platformNames[platform] || `其他系統：${platform}`;

function initialize() {
  if (platform !== "android" && platform !== "ios") {
    status.textContent = "請從 Android 或 iOS 原生 App 啟動；瀏覽器不會被當成裝置系統 API。";
    status.classList.add("error");
    return;
  }

  status.textContent = `已辨識為 ${platformNames[platform]}。按下「讀取目前 Wi-Fi」後，才會請求 OS 提供連線資訊。`;
  readButton.disabled = false;
  // System-mediated sharing can still work when metadata permission is denied
  // or the device is not currently connected to Wi-Fi.
  shareButton.disabled = false;
}

async function readCurrentConnection() {
  readButton.disabled = true;
  status.classList.remove("error");
  status.textContent = "正在呼叫原生 Wi-Fi API…";
  try {
    // OS was detected before this user-initiated native API call.
    const connection = await NativeWifiBridge.getCurrentConnection();
    if (!connection.connected || !connection.ssid) {
      networkTitle.textContent = "未連線至 Wi-Fi";
      networkMeta.textContent = "請先在系統設定連線至 Wi-Fi，再重新整理。";
      status.textContent = connection.message || "OS API 沒有回傳目前網路名稱。";
      return;
    }
    networkTitle.textContent = connection.ssid;
    networkMeta.textContent = connection.securityType
      ? `安全性：${connection.securityType}`
      : "安全性：由 OS 隱藏或無法辨識";
    status.textContent = "已先辨識 OS，再透過原生系統 API 取得目前連線資訊。密碼不會由本 API 讀取。";
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "OS 系統 API 呼叫失敗。";
    status.classList.add("error");
  } finally {
    readButton.disabled = false;
  }
}

readButton.addEventListener("click", () => void readCurrentConnection());

shareButton.addEventListener("click", async () => {
  shareButton.disabled = true;
  try {
    const result = await NativeWifiBridge.openSystemWifiShare();
    status.textContent = result.message;
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "無法開啟系統分享流程。";
    status.classList.add("error");
  } finally {
    shareButton.disabled = false;
  }
});

initialize();
