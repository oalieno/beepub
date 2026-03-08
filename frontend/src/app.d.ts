import type { UserOut } from "$lib/types";
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
