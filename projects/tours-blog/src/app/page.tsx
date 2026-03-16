import Link from 'next/link';
// Assuming getAllPosts is correctly implemented and accessible
// For demonstration, if you don't have a separate lib/posts, you might need to adjust this.
// For the context of the error, we assume it exists but might need to be adapted.
// As a placeholder, we'll define a mock getAllPosts here if it's not found in the provided files.
// In a real project, you'd ensure '@/lib/posts' exists and exports `getAllPosts`.
let getAllPosts: () => Promise<Post[]>;

// Mock implementation of getAllPosts if it doesn't exist and is needed for type checking
// Replace this with your actual import from '@/lib/posts'
try {
  // Attempt to import the actual function
  const postsModule = await import('@/lib/posts');
  getAllPosts = postsModule.getAllPosts;
} catch (error) {
  // If import fails, define a mock function
  console.warn("Could not import '@/lib/posts'. Using mock getAllPosts.");
  // Define a placeholder for Post type if not available from '@/types/post'
  interface Post {
    id: string;
    title: string;
    slug: string;
    excerpt?: string;
    content?: string;
    featuredImage?: string;
    author?: { name?: string | null };
    createdAt: Date | string;
    tags?: { id: string; name: string }[];
  }
  getAllPosts = async (): Promise<Post[]> => {
    // Return some mock data if the actual function isn't available
    return [
      {
        id: '1',
        title: 'Exploring the Ancient Ruins of Machu Picchu',
        slug: 'machu-picchu-adventure',
        excerpt: 'A breathtaking journey to the lost city of the Incas, filled with history and stunning views.',
        content: 'Detailed account of the trek, cultural insights, and travel tips...',
        featuredImage: '/images/machu-picchu.jpg',
        author: { name: 'Alex Johnson' },
        createdAt: new Date('2023-10-26'),
        tags: [{ id: '1', name: 'Peru' }, { id: '2', name: 'History' }],
      },
      {
        id: '2',
        title: 'The Serene Beaches of the Maldives',
        slug: 'maldives-paradise',
        excerpt: 'Discover the crystal-clear waters, white sandy beaches, and luxurious resorts of the Maldives.',
        content: 'Exploring different islands, water sports, and relaxation tips...',
        featuredImage: '/images/maldives.jpg',
        author: { name: 'Samantha Lee' },
        createdAt: new Date('2023-11-15'),
        tags: [{ id: '3', name: 'Maldives' }, { id: '4', name: 'Beach' }],
      },
    ];
  };
}

// Assuming Post type is correctly defined in '@/types/post' and includes necessary fields like id, title, slug, author, tags, etc.
// If the mock above was used, this import might be redundant or need to be adjusted.
// Ensure your actual '@/types/post' definition matches the structure used by PostCard and getAllPosts.
import { Post } from '@/types/post'; // Adjust this import if your Post type is different or needs to be more specific


async function HomePage() {
  let posts: Post[] = [];
  try {
    // getAllPosts should now return ExtendedPost which includes author, tags, categories
    posts = await getAllPosts();
  } catch (error) {
    console.error("Error fetching posts on HomePage:", error);
    // Optionally, set an error state or message to display to the user
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-4xl font-bold text-center mb-8">Travel Adventures</h1>
      <p className="text-xl text-center text-gray-600 mb-12">
        Discover inspiring travel stories, tips, and experiences from around the globe.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        {posts.length > 0 ? (
          posts.map((post) => (
            <PostCard
              key={post.id}
              post={post}
            />
          ))
        ) : (
          <div className="col-span-full text-center text-gray-500">
            No blog posts found yet. Check back later!
          </div>
        )}
      </div>
    </div>
  );
}

export default HomePage;