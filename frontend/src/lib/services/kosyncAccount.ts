/**
 * The single global external-kosync account — serverless local mode only.
 *
 * Device-owned like the OPDS catalogs, and deliberately never cleared when a
 * BeePub server is connected: resolve.ts just stops reading it (connected
 * means BeePub IS the kosync server), and it revives on disconnect. Only the
 * md5(password) userkey is stored, never the plaintext — though for kosync
 * that hash IS the credential, and Preferences offers no secure storage,
 * same posture as the auth tokens in localStorage.
 */
import { Preferences } from "@capacitor/preferences";

const ACCOUNT_KEY = "kosync-account";

export interface KosyncAccount {
  /** https, trailing slashes stripped — endpoint paths are fixed. */
  serverUrl: string;
  username: string;
  /** md5(password), lowercase hex — sent as x-auth-key verbatim. */
  userkey: string;
  /** Minted once, stable across re-logins — suppresses own-echo prompts. */
  deviceId: string;
  /** false = manual mode: no pull-on-open, no push-on-save; the reader's
   *  manual pull/push buttons are the only sync triggers (the KOReader
   *  auto-sync toggle). */
  autoSync: boolean;
  addedAt: string;
}

export async function getKosyncAccount(): Promise<KosyncAccount | null> {
  const { value } = await Preferences.get({ key: ACCOUNT_KEY });
  if (!value) return null;
  try {
    const account = JSON.parse(value) as KosyncAccount;
    // Accounts stored before the toggle existed sync automatically.
    account.autoSync = account.autoSync !== false;
    return account;
  } catch {
    return null;
  }
}

export async function setKosyncAccount(input: {
  serverUrl: string;
  username: string;
  userkey: string;
}): Promise<KosyncAccount> {
  const existing = await getKosyncAccount();
  const account: KosyncAccount = {
    serverUrl: input.serverUrl.trim().replace(/\/+$/, ""),
    username: input.username.trim(),
    userkey: input.userkey,
    deviceId: existing?.deviceId ?? crypto.randomUUID(),
    autoSync: existing?.autoSync ?? true,
    addedAt: existing?.addedAt ?? new Date().toISOString(),
  };
  await Preferences.set({ key: ACCOUNT_KEY, value: JSON.stringify(account) });
  return account;
}

export async function setKosyncAutoSync(
  autoSync: boolean,
): Promise<KosyncAccount | null> {
  const existing = await getKosyncAccount();
  if (!existing) return null;
  const account: KosyncAccount = { ...existing, autoSync };
  await Preferences.set({ key: ACCOUNT_KEY, value: JSON.stringify(account) });
  return account;
}

export async function clearKosyncAccount(): Promise<void> {
  await Preferences.remove({ key: ACCOUNT_KEY });
}
