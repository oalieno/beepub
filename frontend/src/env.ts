import { defineEnvVars } from "@sveltejs/kit/env";

export const variables = defineEnvVars({
  BACKEND_URL: {
    description:
      "Where the server-side renderer reaches the backend (the compose service by default).",
    schema: (input: string | undefined) => input || "http://backend:8000",
  },
});
