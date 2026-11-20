export interface CurrentWifiConnection {
  connected: boolean;
  ssid?: string;
  securityType?: string;
  message?: string;
}

export interface OpenShareResult {
  opened: boolean;
  message: string;
}

export interface NativeWifiBridgePlugin {
  getCurrentConnection(): Promise<CurrentWifiConnection>;
  openSystemWifiShare(): Promise<OpenShareResult>;
}
