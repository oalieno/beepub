export const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "e2e-admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-password-123",
};

/** Cookie state written by global-setup, consumed via test.use(). */
export const ADMIN_STATE = "e2e/.auth/admin.json";

export const LIBRARY_NAME = "E2E Library";
