import Link from 'next/link';
import Image from 'next/image';
import { Button } from '@/components/ui/Button/Button';
import { site } from '@/config/site';

export const Navbar = () => {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <nav className="container flex h-14 items-center justify-between py-4">
        <div className="flex items-center space-x-4 lg:space-x-6">
          <Link href="/" className="flex items-center space-x-2">
            <Image src="/logo.svg" alt="Logo" width={30} height={30} />
            <span className="inline-block font-bold">{site.name}</span>
          </Link>
          <nav className="hidden gap-6 text-sm font-medium md:flex">
            <Link
              href="/blog"
              className="transition-colors hover:text-foreground/80 text-foreground"
            >
              Blog
            </Link>
            <Link
              href="/about"
              className="transition-colors hover:text-foreground/80 text-foreground"
            >
              About
            </Link>
            <Link
              href="/contact"
              className="transition-colors hover:text-foreground/80 text-foreground"
            >
              Contact
            </Link>
          </nav>
        </div>
        <div className="flex items-center space-x-2">
          <Button variant="ghost" size="sm">
            Login
          </Button>
          <Button size="sm">Sign Up</Button>
        </div>
      </nav>
    </header>
  );
};