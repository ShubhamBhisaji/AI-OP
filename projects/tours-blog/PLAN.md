# PLAN: TOURS

**Type:** webapp  
**Description:** BLOG to share i traveling details and sharing expriences

# Product Requirements Document: TOURS

## Overview

TOURS is a web application designed to be a personal travel blog platform. It allows users to share their travel experiences, itineraries, photos, and insights with a wider audience. The primary goal is to create a visually appealing and user-friendly platform for travel enthusiasts to document and discover new destinations and adventures.

## Type

Web Application

## Tech Stack

*   **Frontend:** React, Next.js (for SSR/SSG and routing), Tailwind CSS (for styling)
*   **Backend:** Node.js, Express.js
*   **Database:** PostgreSQL (with Prisma ORM for efficient data management)
*   **Image/Asset Storage:** Cloudinary (for optimized image delivery and storage)
*   **Deployment:** Vercel (for frontend), Render/AWS EC2 (for backend and database)

## Core Features

1.  **User Authentication:**
    *   Secure user registration and login (email/password, potentially OAuth integration later).
    *   User profile management (name, bio, profile picture, social media links, travel goals, past trips).

2.  **Blog Post Creation & Management:**
    *   Rich Text Editor: WYSIWYG editor for creating engaging blog posts with formatting options (bold, italics, headings, lists, links). Supports embedding images and other media.
    *   Markdown Support: Ability to write posts using Markdown for more control.
    *   Image and Media Uploads: Seamless integration for uploading and embedding images, videos, and other media within posts.
    *   Tagging and Categorization: Ability to assign tags and categories to blog posts for better organization and discoverability.
    *   Drafting and Publishing: Functionality to save posts as drafts and publish them when ready.
    *   Post Editing and Deletion: Ability to edit and delete existing posts.

3.  **Blog Post Display:**
    *   Homepage: A feed displaying recent blog posts, potentially with featured posts.
    *   Individual Post View: A dedicated page for each blog post, displaying content, images, author information, date, and tags.
    *   Category/Tag Archives: Pages listing all posts associated with a specific category or tag.
    *   Search Functionality: Ability to search for blog posts by keywords, titles, or tags.

4.  **User Experience & Engagement:**
    *   Responsive Design: The application will be fully responsive and accessible across various devices (desktops, tablets, mobile phones).
    *   Image Optimization: Images will be optimized for web delivery to ensure fast loading times.
    *   SEO Friendly URLs and Meta Tags: Each post will have SEO-friendly URLs and meta tags for better search engine visibility.
    *   Content Moderation: Users can report inappropriate content. Posts may be subject to an approval process (future consideration).

5.  **Admin Panel (Basic):**
    *   Dashboard: Overview of blog posts, users.
    *   User Management (basic): View and potentially disable users.
    *   Content Moderation: Tools to review reported posts and take action.

## File Structure

*   `/.next/` — Next.js build output (generated)
*   `/public/` — Static assets (images, fonts, favicon)
    *   `public/favicon.ico` — Site favicon.
    *   `public/logo.svg` — Site logo for branding.
*   `/src/` — Application source code
    *   `src/app/` — Next.js App Router entry points and layouts
        *   `src/app/layout.tsx` — Root layout component for the entire application.
        *   `src/app/page.tsx` — Homepage component, displaying the blog feed.
        *   `src/app/blog/[slug]/page.tsx` — Dynamic route for individual blog post display.
        *   `src/app/categories/[category]/page.tsx` — Dynamic route for category archive pages.
        *   `src/app/tags/[tag]/page.tsx` — Dynamic route for tag archive pages.
        *   `src/app/api/auth/[...nextauth]/route.ts` — NextAuth.js API routes for authentication.
        *   `src/app/api/posts/route.ts` — API route for fetching blog posts.
        *   `src/app/api/posts/[id]/route.ts` — API route for individual post operations (create, update, delete).
        *   `src/app/admin/page.tsx` — Admin dashboard.
        *   `src/app/admin/users/page.tsx` — Admin user management page.
        *   `src/app/admin/posts/page.tsx` — Admin post moderation page.
    *   `src/components/` — Reusable React components
        *   `src/components/ui/Button/Button.tsx` — Reusable button component.
        *   `src/components/ui/Input/Input.tsx` — Reusable input field component.
        *   `src/components/ui/Card/Card.tsx` — Reusable card component for displaying post summaries.
        *   `src/components/layout/Navbar/Navbar.tsx` — Navigation bar component.
        *   `src/components/layout/Footer/Footer.tsx` — Footer component.
        *   `src/components/editor/RichTextEditor.tsx` — Component for rich text editing.
        *   `src/components/posts/PostCard.tsx` — Component for displaying a single post summary in lists.
        *   `src/components/posts/PostDetail.tsx` — Component for displaying a full blog post.
        *   `src/components/auth/LoginForm.tsx` — Component for user login form.
        *   `src/components/auth/RegisterForm.tsx` — Component for user registration form.
        *   `src/components/common/Tag.tsx` — Component for displaying a single tag.
        *   `src/components/admin/UserTable.tsx` — Component to display user data in admin panel.
        *   `src/components/admin/ReportedPostList.tsx` — Component to display reported posts in admin panel.
    *   `src/config/` — Application configuration files
        *   `src/config/site.ts` — Site-wide configuration (site name, URLs, etc.).
        *   `src/config/env.ts` — Environment variable configuration and validation.
    *   `src/lib/` — Utility functions and libraries
        *   `src/lib/db.ts` — Database connection and Prisma client setup.
        *   `src/lib/auth.ts` — Authentication-related utility functions.
        *   `src/lib/utils.ts` — General utility functions.
        *   `src/lib/posts.ts` — Functions for interacting with the blog post data.
        *   `src/lib/images.ts` — Image upload and processing utilities (e.g., Cloudinary integration).
        *   `src/lib/admin.ts` — Utility functions for admin panel operations.
    *   `src/styles/globals.css` — Global CSS styles.
    *   `src/types/` — TypeScript type definitions
        *   `src/types/post.ts` — Type definitions for blog post objects.
        *   `src/types/user.ts` — Type definitions for user objects.
        *   `src/types/admin.ts` — Type definitions for admin-related data.
*   `.env.local` — Local environment variables (e.g., database URL, API keys).
*   `.gitignore` — Specifies intentionally untracked files that Git should ignore.
*   `next.config.js` — Next.js configuration file.
*   `package.json` — Project dependencies and scripts.
*   `postcss.config.js` — PostCSS configuration for Tailwind CSS.
*   `prisma/` — Prisma schema and migration files
    *   `prisma/schema.prisma` — Prisma database schema definition.
    *   `prisma/migrations/` — Database migration scripts.
*   `README.md` — Project description and setup instructions.
*   `tailwind.config.ts` — Tailwind CSS configuration file.
*   `tsconfig.json` — TypeScript compiler options.

## Build Notes

1.  **Environment Variables:** Ensure `.env.local` is populated with necessary environment variables, including `DATABASE_URL`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, and `CLOUDINARY_URL`.
2.  **Database Setup:**
    *   Install PostgreSQL.
    *   Create a database for the application.
    *   Run `npx prisma db push` to create tables based on the `prisma/schema.prisma` file.
    *   Run `npx prisma migrate dev --name init` for initial migration.
3.  **Dependencies:** Run `npm install` or `yarn install` to install all project dependencies.
4.  **Development Server:** Start the development server with `npm run dev` or `yarn dev`.
5.  **Build for Production:** Build the application for production with `npm run build` or `yarn build`.
6.  **Start Production Server:** Start the production server with `npm run start` or `yarn start`.
7.  **Image Uploads:** Configure Cloudinary credentials in `.env.local` for image hosting and optimization.

---

## Clarifications

**Q:** What level of rich text editor functionality is required? For example, should it support inline image editing, embedding of custom HTML blocks, or specific heading levels beyond H1-H6?  
**A:** any suitable

**Q:** Beyond basic user profiles, what specific profile fields are envisioned for users (e.g., social media links, travel goals, past trips)?  
**A:** all

**Q:** Will there be a need for content moderation workflows, such as reporting mechanisms for inappropriate content or an approval process for published posts, even in the initial release?  
**A:** yes

