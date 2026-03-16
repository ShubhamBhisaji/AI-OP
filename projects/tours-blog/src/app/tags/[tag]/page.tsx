import { Metadata } from 'next';
import { Post } from '@prisma/client';
import { getPostsByTag } from '@/lib/posts';
import PostCard from '@/components/posts/PostCard';
import Tag from '@/components/common/Tag';

interface TagPageProps {
  params: {
    tag: string;
  };
}

export async function generateMetadata({ params }: TagPageProps): Promise<Metadata> {
  const tagName = params.tag;
  return {
    title: `Posts tagged with "${tagName}"`,
    description: `Discover travel experiences tagged with "${tagName}" on TOURS.`,
  };
}

export default async function TagPage({ params }: TagPageProps) {
  const tagName = decodeURIComponent(params.tag);
  const posts: Post[] = await getPostsByTag(tagName);

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-4xl font-bold mb-6">
        Posts tagged with: <Tag name={tagName} />
      </h1>
      {posts.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {posts.map((post) => (
            <PostCard key={post.id} post={post} />
          ))}
        </div>
      ) : (
        <p className="text-lg text-gray-600">No posts found for this tag.</p>
      )}
    </div>
  );
}