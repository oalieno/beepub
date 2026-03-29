import { get, post } from "./client";
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
};
