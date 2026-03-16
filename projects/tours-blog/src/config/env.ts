import { createEnv } from "@t3-oss/next-experimental/next-runtime";
import { z } from "zod";

export const env = createEnv({
  server: {
    DATABASE_URL: z.string().url(),
    NEXTAUTH_SECRET: z.string(),
    NEXTAUTH_URL: z.string().url(),
    CLOUDINARY_CLOUD_NAME: z.string(),
    CLOUDINARY_API_KEY: z.string(),
    CLOUDINARY_API_SECRET: z.string(),
  },
  client: {
    // CLOUDINARY_URL: z.string().url(), // Not needed for client-side, Cloudinary SDK uses env vars
  },
  runtime: "nodejs",
  skipValidation:
    !!process.env.CI || process.env.NODE_ENV === "test",
});