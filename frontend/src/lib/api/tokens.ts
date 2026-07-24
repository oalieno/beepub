import { get, post, del } from "./client";
import type { ApiToken, ApiTokenCreated } from "$lib/types";

export const tokensApi = {
  list: () => get("/tokens") as Promise<ApiToken[]>,
  create: (name: string) =>
    post("/tokens", { name }) as Promise<ApiTokenCreated>,
  revoke: (id: string) => del(`/tokens/${id}`),
};
