/**
 * The device's stable identity for server-side per-device records (the
 * reading-activity ledger). Minted once, survives re-logins and server
 * switches; a reinstall wipes Preferences and mints a new one, which is
 * exactly what the ledger's REPLACE semantics rely on. Distinct from the
 * kosync account's deviceId — that one lives and dies with the account.
 */
import { Preferences } from "@capacitor/preferences";

const KEY = "device-id";

let cached: string | null = null;

export async function getDeviceId(): Promise<string> {
  if (cached) return cached;
  const { value } = await Preferences.get({ key: KEY });
  if (value) {
    cached = value;
    return value;
  }
  const id = crypto.randomUUID();
  await Preferences.set({ key: KEY, value: id });
  cached = id;
  return id;
}
