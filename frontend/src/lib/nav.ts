import { authStore } from "$lib/stores/auth";
import { isNative } from "$lib/platform";
import { isOnline } from "$lib/services/network";
import { toastStore } from "$lib/stores/toast";
import { UserRole } from "$lib/types";
import { get } from "svelte/store";

export function getIsAdmin(): boolean {
  return get(authStore).user?.role === UserRole.Admin;
}

export function getOnline(): boolean {
  return get(isOnline);
}

export function handleDisabledClick(e: Event) {
  e.preventDefault();
  toastStore.info("Available when online");
}

export { isNative, isOnline, authStore };
