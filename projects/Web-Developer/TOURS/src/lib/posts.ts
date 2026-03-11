import { Post, Prisma, Author, Tag, Category } from '@prisma/client';
import { prisma } from '@/lib/db';
// Assuming uploadImage is correctly implemented elsewhere and not causing build issues for now.
// import { uploadImage } from '@/lib/images';

// Define a more specific type for the included author, tags, and categories
interface ExtendedPost extends Post {
  author: Author;
  tags: Tag[];
  categories: Category[];
}

export interface CreatePostData {
  title: string;
  content: string;
  authorId: string;
  tags?: string[];
  categories?: string[];
  published?: boolean;
  slug?: string;
  featuredImage?: string;
}

export interface UpdatePostData {
  title?: string;
  content?: string;
  tags?: string[];
  categories?: string[];
  published?: boolean;
  slug?: string;
  featuredImage?: string;
}

export const getAllPosts = async (publishedOnly: boolean = true): Promise<ExtendedPost[]> => {
  const where: Prisma.PostWhereInput = publishedOnly ? { published: true } : {};
  return prisma.post.findMany({
    where,
    orderBy: { createdAt: 'desc' },
    include: { author: true, tags: true, categories: true },
  }) as Promise<ExtendedPost[]>;
};

export const getPostBySlug = async (slug: string): Promise<ExtendedPost | null> => {
  return prisma.post.findUnique({
    where: { slug },
    include: { author: true, tags: true, categories: true },
  }) as Promise<ExtendedPost | null>;
};

export const getPostsByCategory = async (categoryName: string): Promise<ExtendedPost[]> => {
  return prisma.post.findMany({
    where: {
      categories: {
        some: { name: categoryName },
      },
      published: true,
    },
    orderBy: { createdAt: 'desc' },
    include: { author: true, tags: true, categories: true },
  }) as Promise<ExtendedPost[]>;
};

export const getPostsByTag = async (tagName: string): Promise<ExtendedPost[]> => {
  return prisma.post.findMany({
    where: {
      tags: {
        some: { name: tagName },
      },
      published: true,
    },
    orderBy: { createdAt: 'desc' },
    include: { author: true, tags: true, categories: true },
  }) as Promise<ExtendedPost[]>;
};

export const createPost = async (data: CreatePostData): Promise<ExtendedPost> => {
  const { tags, categories, ...rest } = data;

  const postData: Prisma.PostCreateInput = {
    ...rest,
    author: { connect: { id: data.authorId } },
    tags: tags ? { connectOrCreate: tags.map(tag => ({ where: { name: tag }, create: { name: tag } })) } : undefined,
    categories: categories ? { connectOrCreate: categories.map(cat => ({ where: { name: cat }, create: { name: cat } })) } : undefined,
  };

  return prisma.post.create({ data: postData }) as Promise<ExtendedPost>;
};

export const updatePost = async (id: string, data: UpdatePostData): Promise<ExtendedPost> => {
  const { tags, categories, ...rest } = data;

  const updatePayload: Prisma.PostUpdateInput = {
    ...rest,
    tags: tags ? { set: [], connectOrCreate: tags.map(tag => ({ where: { name: tag }, create: { name: tag } })) } : undefined,
    categories: categories ? { set: [], connectOrCreate: categories.map(cat => ({ where: { name: cat }, create: { name: cat } })) } : undefined,
  };

  return prisma.post.update({
    where: { id },
    data: updatePayload,
  }) as Promise<ExtendedPost>;
};

export const deletePost = async (id: string): Promise<ExtendedPost> => {
  return prisma.post.delete({ where: { id } }) as Promise<ExtendedPost>;
};

export const publishPost = async (id: string): Promise<ExtendedPost> => {
  return prisma.post.update({ where: { id }, data: { published: true } }) as Promise<ExtendedPost>;
};

export const unpublishPost = async (id: string): Promise<ExtendedPost> => {
  return prisma.post.update({ where: { id }, data: { published: false } }) as Promise<ExtendedPost>;
};

export const searchPosts = async (query: string): Promise<ExtendedPost[]> => {
  return prisma.post.findMany({
    where: {
      OR: [
        { title: { contains: query, mode: 'insensitive' } },
        { content: { contains: query, mode: 'insensitive' } },
        { tags: { some: { name: { contains: query, mode: 'insensitive' } } } },
        { categories: { some: { name: { contains: query, mode: 'insensitive' } } } },
      ],
      published: true,
    },
    include: { author: true, tags: true, categories: true },
  }) as Promise<ExtendedPost[]>;
};

export const getFeaturedPosts = async (): Promise<ExtendedPost[]> => {
  return prisma.post.findMany({
    where: {
      published: true,
      isFeatured: true,
    },
    orderBy: { createdAt: 'desc' },
    include: { author: true, tags: true, categories: true },
  }) as Promise<ExtendedPost[]>;
};