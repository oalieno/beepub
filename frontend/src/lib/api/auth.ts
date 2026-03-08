import { get, post } from "./client";
import type { TokenResponse, UserOut } from "$lib/types";

export const authApi = {
  register: (body: { username: string; password: string; email?: string }) =>
    post("/auth/register", body) as Promise<UserOut>,

  login: (username: string, password: string) =>
    post(
      "/auth/login",
      new URLSearchParams({ username, password, grant_type: "password" }),
      null,
      { "Content-Type": "application/x-www-form-urlencoded" },
    ) as Promise<TokenResponse>,

  me: (token: string) => get("/auth/me", token) as Promise<UserOut>,
};
