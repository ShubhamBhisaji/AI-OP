import React from 'react';
import Image from 'next/image';
import Link from 'next/link';
import Tag from '@/components/common/Tag';
// Ensure that the Post type here matches the data structure returned by your API,
// especially regarding nested objects like author, tags, and categories.
// It should at least have id, title, slug, author (with name), tags (with id and name), createdAt.
import { Post } from '@/types/post';
import { formatDate, cn, generateSlug } from '@/lib/utils';

interface PostCardProps {
  post: Post;
}

const PostCard: React.FC<PostCardProps> = ({ post }) => {
  // Ensure slug exists before creating the link, or provide a default.
  // It's safer to assume a slug will be generated or present. If not, handle it gracefully.
  const postSlug = post.slug || generateSlug(post.title); // Fallback to generating slug from title if slug is missing

  return (
    <div className="border rounded-lg shadow-sm overflow-hidden hover:shadow-md transition-shadow duration-200 ease-in-out group">
      {post.featuredImage && ( // Assuming featuredImage is the field for the image URL
        <Link href={`/blog/${postSlug}`}>
          <div className="relative w-full h-48 md:h-64">
            <Image
              src={post.featuredImage}
              alt={post.title}
              fill
              objectFit="cover"
              className="group-hover:scale-105 transition-transform duration-300 ease-in-out"
            />
          </div>
        </Link>
      )}
      <div className="p-4">
        <Link href={`/blog/${postSlug}`}>
          <h3 className="text-xl font-semibold mb-2 text-gray-800 dark:text-gray-200 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors duration-200 ease-in-out">
            {post.title}
          </h3>
        </Link>
        <p className="text-gray-600 dark:text-gray-300 mb-3 line-clamp-3">
          {post.excerpt || (post.content ? post.content.substring(0, 100) + (post.content.length > 100 ? '...' : '') : 'No content available.')}
        </p>
        <div className="flex justify-between items-center text-sm text-gray-500 dark:text-gray-400 mb-3">
          <span>By {post.author?.name || 'Anonymous'}</span>
          <span>{post.createdAt ? formatDate(post.createdAt) : 'Unknown date'}</span>
        </div>
        {post.tags && post.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {post.tags.slice(0, 3).map((tag) => (
              <Tag key={tag.id} name={tag.name} />
            ))}
            {post.tags.length > 3 && (
              <span className="text-xs text-gray-500 dark:text-gray-400">+{post.tags.length - 3} more</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default PostCard;