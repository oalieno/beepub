import { get, post, put } from "./client";
import type { LoginResponse, TierBand, UserOut } from "$lib/types";

export const authApi = {
  register: (body: { username: string; password: string }) =>
    post("/auth/register", body) as Promise<UserOut>,

  login: (username: string, password: string) =>
    post(
      "/auth/login",
      new URLSearchParams({ username, password, grant_type: "password" }),
      { "Content-Type": "application/x-www-form-urlencoded" },
    ) as Promise<LoginResponse>,

  me: () => get("/auth/me") as Promise<UserOut>,

  registrationStatus: () =>
    get("/auth/registration-status") as Promise<{
      registration_enabled: boolean;
      first_user: boolean;
    }>,

  changePassword: (currentPassword: string, newPassword: string) =>
    put("/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    }),

  updateUsername: (newUsername: string) =>
    put("/auth/username", { new_username: newUsername }) as Promise<UserOut>,

  // null tier_theme resets to the default preset
  updateTierTheme: (tierTheme: TierBand[] | null) =>
    put("/auth/tier-theme", { tier_theme: tierTheme }) as Promise<UserOut>,
};
