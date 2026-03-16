export const siteConfig = {
  name: "TOURS",
  description: "A personal travel blog platform to share your traveling details and experiences.",
  url: "https://tours-blog.vercel.app",
  links: {
    twitter: "https://twitter.com/shadcn",
    github: "https://github.com/shadcn-ui/ui",
    docs: "https://ui.shadcn.com/",
  },
  mainNav: [
    {
      title: "Home",
      href: "/",
    },
    {
      title: "Explore",
      href: "/explore",
    },
    {
      title: "About",
      href: "/about",
    },
  ],
  sidebarNav: [
    {
      title: "Posts",
      href: "/dashboard/posts",
      icon: "post",
    },
    {
      title: "Users",
      href: "/dashboard/users",
      icon: "user",
    },
    {
      title: "Categories",
      href: "/dashboard/categories",
      icon: "category",
    },
    {
      title: "Tags",
      href: "/dashboard/tags",
      icon: "tag",
    },
  ],
};