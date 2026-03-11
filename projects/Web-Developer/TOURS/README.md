# TOURS: Personal Travel Blog

TOURS is a web application designed to be a personal travel blog platform. It allows users to share their travel experiences, itineraries, photos, and insights with a wider audience. The primary goal is to create a visually appealing and user-friendly platform for travel enthusiasts to document and discover new destinations and adventures.

## Tech Stack

*   **Frontend:** React, Next.js, Tailwind CSS
*   **Backend:** Node.js, Express.js
*   **Database:** PostgreSQL (with Prisma ORM)
*   **Image/Asset Storage:** Cloudinary
*   **Deployment:** Vercel, Render/AWS EC2

## Core Features

*   **User Authentication:** Secure registration, login, and profile management.
*   **Blog Post Creation & Management:** Rich Text Editor, Markdown Support, image uploads, tagging, categorization, drafting, publishing, editing, and deletion.
*   **Blog Post Display:** Homepage feed, individual post view, category/tag archives, and search functionality.
*   **User Experience & Engagement:** Responsive Design, Image Optimization, SEO Friendly URLs and Meta Tags, Content Moderation (reporting).
*   **Admin Panel (Basic):** Dashboard, User Management, Content Moderation tools.

## File Structure

The project follows a standard Next.js structure with added configurations for backend and database management.

*   `/.next/`
*   `/public/`
    *   `public/favicon.ico`
    *   `public/logo.svg`
*   `/src/`
    *   `src/app/`
        *   `src/app/layout.tsx`
        *   `src/app/page.tsx`
        *   `src/app/blog/[slug]/page.tsx`
        *   `src/app/categories/[category]/page.tsx`
        *   `src/app/tags/[tag]/page.tsx`
        *   `src/app/api/auth/[...nextauth]/route.ts`
        *   `src/app/api/posts/route.ts`
        *   `src/app/api/posts/[id]/route.ts`
        *   `src/app/admin/page.tsx`
        *   `src/app/admin/users/page.tsx`
        *   `src/app/admin/posts/page.tsx`
    *   `src/components/`
        *   `src/components/ui/Button/Button.tsx`
        *   `src/components/ui/Input/Input.tsx`
        *   `src/components/ui/Card/Card.tsx`
        *   `src/components/layout/Navbar/Navbar.tsx`
        *   `src/components/layout/Footer/Footer.tsx`
        *   `src/components/editor/RichTextEditor.tsx`
        *   `src/components/posts/PostCard.tsx`
        *   `src/components/posts/PostDetail.tsx`
        *   `src/components/auth/LoginForm.tsx`
        *   `src/components/auth/RegisterForm.tsx`
        *   `src/components/common/Tag.tsx`
        *   `src/components/admin/UserTable.tsx`
        *   `src/components/admin/ReportedPostList.tsx`
    *   `src/config/`
        *   `src/config/site.ts`
        *   `src/config/env.ts`
    *   `src/lib/`
        *   `src/lib/db.ts`
        *   `src/lib/auth.ts`
        *   `src/lib/utils.ts`
        *   `src/lib/posts.ts`
        *   `src/lib/images.ts`
        *   `src/lib/admin.ts`
    *   `src/styles/globals.css`
    *   `src/types/`
        *   `src/types/post.ts`
        *   `src/types/user.ts`
        *   `src/types/admin.ts`
*   `.env.local`
*   `.gitignore`
*   `next.config.js`
*   `package.json`
*   `postcss.config.js`
*   `prisma/`
    *   `prisma/schema.prisma`
    *   `prisma/migrations/`
*   `README.md`
*   `tailwind.config.ts`
*   `tsconfig.json`

## Setup and Running

### Prerequisites

*   Node.js (v18 or higher recommended)
*   PostgreSQL
*   Cloudinary Account

### Environment Variables

1.  Create a `.env.local` file in the root of the project.
2.  Populate it with the following variables:
    ```env
    DATABASE_URL="postgresql://user:password@host:port/database?schema=public"
    NEXTAUTH_SECRET="your_super_secret_key_for_nextauth"
    NEXTAUTH_URL="http://localhost:3000" # Or your development server URL
    CLOUDINARY_URL="cloudinary://api_key:api_secret@cloud_name"
    ```
    Replace the placeholders with your actual credentials and configuration.

### Database Setup

1.  Install PostgreSQL and create a database for the TOURS application.
2.  Set up Prisma:
    ```bash
    npm install
    npx prisma db push
    npx prisma migrate dev --name init
    ```

### Running the Development Server

```bash
npm run dev
```

The application will be accessible at `http://localhost:3000`.

### Building for Production

```bash
npm run build
```

### Starting the Production Server

```bash
npm run start
```

## Contributing

We welcome contributions! Please refer to `CONTRIBUTING.md` (not yet created) for details on how to contribute.

## License

This project is licensed under the MIT License.