import { User, Post } from "@prisma/client";

export type AdminUser = User;

export interface ReportedPost extends Post {
  reporterId: string | null;
  reporter: User | null;
}

export interface AdminDashboardData {
  totalUsers: number;
  totalPosts: number;
  reportedPostsCount: number;
}