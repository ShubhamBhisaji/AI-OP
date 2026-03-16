import Link from 'next/link';
import React from 'react';
import { siteConfig } from '@/config/site'; // Changed import path to use absolute import

const Footer: React.FC = () => {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="bg-gray-800 text-white py-8">
      <div className="container mx-auto px-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div>
            <h3 className="text-lg font-bold mb-4">TOURS</h3>
            <p className="text-gray-400">
              Share your travel experiences and discover new adventures.
            </p>
          </div>
          <div>
            <h3 className="text-lg font-bold mb-4">Quick Links</h3>
            <ul className="space-y-2">
              <li>
                <Link href="/" className="text-gray-400 hover:text-white transition duration-300">
                  Home
                </Link>
              </li>
              <li>
                <Link href="/about" className="text-gray-400 hover:text-white transition duration-300">
                  About
                </Link>
              </li>
              <li>
                <Link href="/contact" className="text-gray-400 hover:text-white transition duration-300">
                  Contact
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h3 className="text-lg font-bold mb-4">Connect</h3>
            <p className="text-gray-400">
              Follow us on social media for travel inspiration.
            </p>
            <div className="flex space-x-4 mt-4">
              <a href={siteConfig.socialLinks?.twitter || '#'} target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-white transition duration-300">
                Twitter
              </a>
              <a href={siteConfig.socialLinks?.instagram || '#'} target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-white transition duration-300">
                Instagram
              </a>
            </div>
          </div>
        </div>
        <div className="border-t border-gray-700 mt-8 pt-8 text-center text-gray-500">
          &copy; {currentYear} {siteConfig.title}. All rights reserved.
        </div>
      </div>
    </footer>
  );
};

export default Footer;