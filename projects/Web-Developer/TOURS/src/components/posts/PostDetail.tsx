import React from 'react';
import Image from 'next/image';
import { Post } from '@/types/post';
import Tag from '../common/Tag';
import { format } from 'date-fns';

interface PostDetailProps {
  post: Post;
}

const PostDetail: React.FC<PostDetailProps> = ({ post }) => {
  const formattedDate = format(new Date(post.createdAt), 'MMMM dd, yyyy');

  return (
    <article className="container mx-auto px-4 py-8">
      <header className="mb-8 text-center">
        <h1 className="text-4xl font-bold mb-2 text-gray-900 dark:text-white">{post.title}</h1>
        <div className="flex justify-center items-center space-x-4 text-gray-600 dark:text-gray-300 mb-4">
          {post.author && (
            <div className="flex items-center space-x-2">
              {post.author.profilePictureUrl && (
                <Image
                  src={post.author.profilePictureUrl}
                  alt={post.author.name}
                  width={32}
                  height={32}
                  className="rounded-full"
                />
              )}
              <span>{post.author.name}</span>
            </div>
          )}
          <time dateTime={post.createdAt}>{formattedDate}</time>
        </div>
        <div className="flex justify-center space-x-2">
          {post.tags.map((tag) => (
            <Tag key={tag.id} name={tag.name} />
          ))}
        </div>
      </header>

      {post.imageUrl && (
        <figure className="mb-8 text-center">
          <Image
            src={post.imageUrl}
            alt={post.title}
            width={800}
            height={400}
            className="rounded-lg shadow-lg mx-auto"
            style={{ objectFit: 'cover' }}
          />
          {post.imageCaption && (
            <figcaption className="text-sm text-gray-500 dark:text-gray-400 mt-2">{post.imageCaption}</figcaption>
          )}
        </figure>
      )}

      <div className="prose lg:prose-xl max-w-none text-gray-800 dark:text-gray-200" dangerouslySetInnerHTML={{ __html: post.content }} />
    </article>
  );
};

export default PostDetail;