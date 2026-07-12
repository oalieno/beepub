import { post } from "./client";

export interface ActivityEntry {
  /** Device-local calendar date, YYYY-MM-DD. */
  date: string;
  seconds: number;
}

export const activityApi = {
  /** Replace this device's per-day reading seconds on the server. */
  sync: (deviceId: string, entries: ActivityEntry[]) =>
    post("/activity/sync", {
      device_id: deviceId,
      entries,
    }) as Promise<{ days: number }>,
};
