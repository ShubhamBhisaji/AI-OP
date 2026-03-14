import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/db";

export type SessionUserContext = {
  id: string;
  role: "ADMIN" | "USER";
};

export async function getSessionUserContext(): Promise<SessionUserContext | null> {
  const session = await getServerSession(authOptions);
  const sessionUserId = (session?.user as { id?: string } | undefined)?.id;
  if (!sessionUserId) {
    return null;
  }

  const user = await prisma.user.findUnique({
    where: { id: sessionUserId },
    select: { role: true },
  });
  if (!user) {
    return null;
  }

  return {
    id: sessionUserId,
    role: user.role,
  };
}

export function isAdmin(user: SessionUserContext | null): boolean {
  return !!user && user.role === "ADMIN";
}
