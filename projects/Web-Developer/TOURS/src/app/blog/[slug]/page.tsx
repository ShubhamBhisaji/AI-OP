import { Metadata } from 'next';
import Image from 'next/image';
import { notFound } from 'next/navigation';
import React from 'react';
import { Tag } from '@/components/common/Tag';
import { getPostBySlug } from '@/lib/posts';
import { Post } from '@/types/post';

interface PostPageParams {
  params: {
    slug: string;
  };
}

export async function generateMetadata({ params }: PostPageParams): Promise<Metadata> {
  try {
    const post = await getPostBySlug(params.slug);
    if (!post) {
      return {
        title: 'Post Not Found',
      };
    }
    return {
      title: post.title,
      description: post.excerpt,
      openGraph: {
        title: post.title,
        description: post.excerpt,
        images: [post.featuredImage || '/placeholder-image.jpg'],
      },
      twitter: {
        card: 'summary_large_image',
        title: post.title,
        description: post.excerpt,
        images: [post.featuredImage || '/placeholder-image.jpg'],
      },
    };
  } catch (error) {
    console.error('Error fetching metadata:', error);
    return {
      title: 'Error Loading Post',
    };
  }
}

export default async function PostPage({ params }: PostPageParams) {
  let post: Post | null = null;
  try {
    post = await getPostBySlug(params.slug);
  } catch (error) {
    console.error(`Error fetching post with slug ${params.slug}:`, error);
    notFound();
  }

  if (!post) {
    notFound();
  }

  return (
    <article className="container mx-auto py-8 px-4">
      <header className="mb-8 text-center">
        <h1 className="text-4xl font-bold mb-2">{post.title}</h1>
        <p className="text-gray-600 mb-4">
          Published on {new Date(post.createdAt).toLocaleDateString()} by {post.author.name}
        </p>
        <div className="flex justify-center gap-2 mb-4">
          {post.tags.map((tag) => (
            <Tag key={tag.id} name={tag.name} />
          ))}
        </div>
        {post.featuredImage && (
          <div className="relative w-full h-96 mx-auto max-w-4xl mb-8 rounded-lg overflow-hidden shadow-lg">
            <Image
              src={post.featuredImage}
              alt={post.title}
              layout="fill"
              objectFit="cover"
              className="rounded-lg"
            />
          </div>
        )}
      </header>

      <main className="prose lg:prose-xl max-w-none mx-auto" dangerouslySetInnerHTML={{ __html: post.content }} />

      <section className="mt-12 border-t pt-8">
        <h2 className="text-2xl font-bold mb-4">About the Author</h2>
        <div className="flex items-center gap-4">
          {post.author.profilePicture && (
            <div className="w-20 h-20 rounded-full overflow-hidden relative">
              <Image src={post.author.profilePicture} alt={post.author.name} layout="fill" objectFit="cover" />
            </div>
          )}
          <div>
            <h3 className="text-xl font-semibold">{post.author.name}</h3>
            <p className="text-gray-700">{post.author.bio || 'No bio available.'}</p>
            {post.author.socialLinks && (
              <div className="flex gap-4 mt-2">
                {post.author.socialLinks.map((link) => (
                  <a key={link.platform} href={link.url} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">
                    {link.platform}
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </article>
  );
}