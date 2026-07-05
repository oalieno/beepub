import { writable } from "svelte/store";

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

interface ConfirmRequest extends ConfirmOptions {
  resolve: (confirmed: boolean) => void;
}

export const confirmRequest = writable<ConfirmRequest | null>(null);

/**
 * Show the shared confirmation dialog (rendered once in the root layout)
 * and resolve with the user's choice. Drop-in replacement for
 * `window.confirm`, e.g. `if (!(await confirmDialog({ title }))) return;`
 */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    confirmRequest.set({
      ...options,
      resolve: (confirmed) => {
        confirmRequest.set(null);
        resolve(confirmed);
      },
    });
  });
}
