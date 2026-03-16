import React from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/Button/Button';
import { revalidatePath } from 'next/cache';
import { prisma } from '@/lib/db';

// Define the Post interface based on Prisma's Post model
// Assuming your Prisma schema has fields like id, title, slug, authorId, publishedAt, and relation to User and tags
interface Post {
  id: string;
  title: string;
  slug: string;
  author?: { name?: string | null; image?: string | null };
  publishedAt: Date | string | null;
  createdAt: Date | string; // Added createdAt for sorting
}

// Mock data and functions for demonstration purposes if they are not provided
// In a real scenario, these would be imported from your data access layer.
async function getAllPosts(): Promise<Post[]> {
  try {
    const posts = await prisma.post.findMany({
      select: {
        id: true,
        title: true,
        slug: true,
        author: {
          select: {
            name: true,
            image: true,
          },
        },
        publishedAt: true,
        createdAt: true, // Include createdAt for sorting
      },
      orderBy: {
        createdAt: 'desc',
      },
    });
    return posts;
  } catch (error) {
    console.error('Error fetching posts:', error);
    // In a real app, you might want to return an empty array or throw an error
    return [];
  }
}

async function deletePost(postId: string): Promise<void> {
  try {
    await prisma.post.delete({
      where: {
        id: postId,
      },
    });
    console.log(`Post with ID ${postId} deleted successfully.`);
  } catch (error) {
    console.error(`Error deleting post with ID ${postId}:`, error);
    // Handle error appropriately, e.g., throw an error
    throw error;
  }
}


async function AdminPostsPage() {
  const posts: Post[] = await getAllPosts();

  // Server action for deleting a post
  const handleDelete = async (postId: string) => {
    'use server';
    await deletePost(postId);
    revalidatePath('/admin/posts');
  };

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-2xl font-bold mb-6">Manage Blog Posts</h1>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Title
              </th>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Author
              </th>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Published Date
              </th>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {posts.map((post) => (
              <tr key={post.id}>
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                  <Link href={`/blog/${post.slug}`} className="hover:underline">
                    {post.title}
                  </Link>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {post.author?.name || 'Unknown'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {post.publishedAt ? new Date(post.publishedAt).toLocaleDateString() : 'Draft'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                  <Link href={`/admin/posts/edit/${post.id}`} className="text-indigo-600 hover:text-indigo-900 mr-4">
                    Edit
                  </Link>
                  <form action={handleDelete.bind(null, post.id)} className="inline">
                    <Button variant="destructive" size="sm">
                      Delete
                    </Button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-6">
        <Link href="/admin/posts/new">
          <Button>Add New Post</Button>
        </Link>
      </div>
    </div>
  );
}

export default AdminPostsPage;