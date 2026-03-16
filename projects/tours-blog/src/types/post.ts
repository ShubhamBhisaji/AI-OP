import { User } from './user';

export interface Post {
  id: string;
  title: string;
  slug: string;
  content: string;
  featuredImage: string | null;
  createdAt: Date;
  updatedAt: Date;
  published: boolean;
  authorId: string;
  author?: User;
  tags: Tag[];
  categories: Category[];
  likes: number;
  views: number;
}

export interface Tag {
  id: string;
  name: string;
  posts?: Post[];
}

export interface Category {
  id: string;
  name: string;
  posts?: Post[];
}

export interface CreatePostPayload {
  title: string;
  content: string;
  featuredImage?: string;
  tags?: string[];
  categories?: string[];
  published?: boolean;
}

export interface UpdatePostPayload {
  title?: string;
  content?: string;
  featuredImage?: string | null;
  tags?: string[];
  categories?: string[];
  published?: boolean;
}