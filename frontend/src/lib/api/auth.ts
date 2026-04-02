import { get, post, put } from "./client";
import type { LoginResponse, UserOut } from "$lib/types";

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
};
