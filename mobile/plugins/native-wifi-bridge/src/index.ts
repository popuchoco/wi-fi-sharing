import { registerPlugin } from "@capacitor/core";
import type { NativeWifiBridgePlugin } from "./definitions";

export const NativeWifiBridge = registerPlugin<NativeWifiBridgePlugin>("NativeWifiBridge");
export * from "./definitions";
