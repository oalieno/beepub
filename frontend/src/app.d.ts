import type { UserOut } from "#lib/types.ts";
declare global {
  namespace App {
    interface Locals {
      user: UserOut | null;
      token: string | null;
    }
    interface PageData {
      user?: UserOut | null;
    }
  }
}
export {};
