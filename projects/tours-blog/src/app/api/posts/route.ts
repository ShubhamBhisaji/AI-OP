import { prisma } from '@/lib/db';
import { NextResponse } from 'next/server';
import { getSessionUserContext, isAdmin } from '@/lib/api-auth';
import { sanitizeRichHtml } from '@/lib/sanitize';

export async function GET() {
  try {
    const user = await getSessionUserContext();
    const posts = await prisma.post.findMany({
      where: isAdmin(user) ? undefined : { published: true },
      orderBy: {
        createdAt: 'desc',
      },
      include: {
        author: {
          select: {
            name: true,
            image: true,
          },
        },
        tags: {
          select: {
            name: true,
          },
        },
      },
    });
    return NextResponse.json(posts);
  } catch (error) {
    console.error('Error fetching posts:', error);
    return NextResponse.json({ error: 'Failed to fetch posts' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const user = await getSessionUserContext();
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { title, content, published, tagIds } = await request.json();

    if (!title || !content) {
      return NextResponse.json({ error: 'Missing required fields' }, { status: 400 });
    }

    const post = await prisma.post.create({
      data: {
        title,
        content: sanitizeRichHtml(content),
        published: published || false,
        authorId: user.id,
        tags: tagIds ? { connect: tagIds.map((tagId: string) => ({ id: tagId })) } : undefined,
      },
    });

    return NextResponse.json(post, { status: 201 });
  } catch (error) {
    console.error('Error creating post:', error);
    return NextResponse.json({ error: 'Failed to create post' }, { status: 500 });
  }
}