import { notFound } from 'next/navigation';
import React from 'react';
import PostCard from '@/components/posts/PostCard';
import { getPostsByCategory } from '@/lib/posts';
import { Button } from '@/components/ui/Button/Button';
import Link from 'next/link';

interface CategoryPageProps {
  params: {
    category: string;
  };
}

const CategoryPage: React.FC<CategoryPageProps> = async ({ params }) => {
  const { category } = params;
  const decodedCategory = decodeURIComponent(category);
  const posts = await getPostsByCategory(decodedCategory);

  if (!posts || posts.length === 0) {
    return (
      <div className="container mx-auto py-16 px-4">
        <h1 className="text-4xl font-bold mb-8">Category: {decodedCategory}</h1>
        <p className="text-xl text-gray-600">No posts found for this category.</p>
        <Button asChild className="mt-6">
          <Link href="/">Go back to Home</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-16 px-4">
      <h1 className="text-4xl font-bold mb-8">Category: {decodedCategory}</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        {posts.map((post) => (
          <PostCard
            key={post.id}
            post={post}
            className="shadow-lg hover:shadow-xl transition-shadow duration-300"
          />
        ))}
      </div>
    </div>
  );
};

export default CategoryPage;