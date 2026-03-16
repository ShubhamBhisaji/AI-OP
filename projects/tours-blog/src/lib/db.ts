import { PrismaClient } from '@prisma/client';

// Ensure PrismaClient is a singleton to avoid multiple connections during hot-reloading.
declare global {
  // eslint-disable-next-line no-var
  var prisma: PrismaClient | undefined;
}

export const prisma =
  global.prisma ||
  new PrismaClient({
    // Optionally add log configurations here if needed for debugging
    // log: ['query', 'info', 'warn', 'error'],
  });

if (process.env.NODE_ENV !== 'production') {
  global.prisma = prisma;
}