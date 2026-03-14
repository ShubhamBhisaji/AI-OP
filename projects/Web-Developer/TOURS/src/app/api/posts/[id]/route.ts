import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/db';
import { getSessionUserContext, isAdmin } from '@/lib/api-auth';
import { sanitizeRichHtml } from '@/lib/sanitize';

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const user = await getSessionUserContext();
    const postId = parseInt(params.id, 10);
    if (isNaN(postId)) {
      return NextResponse.json({ message: 'Invalid post ID' }, { status: 400 });
    }

    const post = await prisma.post.findUnique({
      where: { id: postId },
      include: {
        author: true,
        tags: true,
        categories: true,
      },
    });

    if (!post) {
      return NextResponse.json({ message: 'Post not found' }, { status: 404 });
    }

    if (!post.published && !(isAdmin(user) || user?.id === post.authorId)) {
      return NextResponse.json({ message: 'Not found' }, { status: 404 });
    }

    return NextResponse.json(post, { status: 200 });
  } catch (error) {
    console.error('Error fetching post:', error);
    return NextResponse.json({ message: 'Internal Server Error' }, { status: 500 });
  }
}

export async function PUT(req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const user = await getSessionUserContext();
    if (!user) {
      return NextResponse.json({ message: 'Unauthorized' }, { status: 401 });
    }

    const postId = parseInt(params.id, 10);
    if (isNaN(postId)) {
      return NextResponse.json({ message: 'Invalid post ID' }, { status: 400 });
    }

    const existing = await prisma.post.findUnique({
      where: { id: postId },
      select: { authorId: true },
    });
    if (!existing) {
      return NextResponse.json({ message: 'Post not found' }, { status: 404 });
    }

    if (!isAdmin(user) && existing.authorId !== user.id) {
      return NextResponse.json({ message: 'Forbidden' }, { status: 403 });
    }

    const body = await req.json();
    const { title, content, published, tags, categories } = body;

    const updatedPost = await prisma.post.update({
      where: { id: postId },
      data: {
        title,
        content: typeof content === 'string' ? sanitizeRichHtml(content) : undefined,
        published: published !== undefined ? published : undefined,
        tags: tags ? {
          set: tags.map((tagId: number) => ({ id: tagId })),
        } : undefined,
        categories: categories ? {
          set: categories.map((categoryId: number) => ({ id: categoryId })),
        } : undefined,
      },
      include: {
        author: true,
        tags: true,
        categories: true,
      },
    });

    return NextResponse.json(updatedPost, { status: 200 });
  } catch (error) {
    console.error('Error updating post:', error);
    return NextResponse.json({ message: 'Internal Server Error' }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const user = await getSessionUserContext();
    if (!user) {
      return NextResponse.json({ message: 'Unauthorized' }, { status: 401 });
    }

    const postId = parseInt(params.id, 10);
    if (isNaN(postId)) {
      return NextResponse.json({ message: 'Invalid post ID' }, { status: 400 });
    }

    const existing = await prisma.post.findUnique({
      where: { id: postId },
      select: { authorId: true },
    });
    if (!existing) {
      return NextResponse.json({ message: 'Post not found' }, { status: 404 });
    }

    if (!isAdmin(user) && existing.authorId !== user.id) {
      return NextResponse.json({ message: 'Forbidden' }, { status: 403 });
    }

    await prisma.post.delete({
      where: { id: postId },
    });

    return NextResponse.json({ message: 'Post deleted successfully' }, { status: 200 });
  } catch (error) {
    console.error('Error deleting post:', error);
    return NextResponse.json({ message: 'Internal Server Error' }, { status: 500 });
  }
}