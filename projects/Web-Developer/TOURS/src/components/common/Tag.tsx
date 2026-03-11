import React from 'react';
import Link from 'next/link';

interface TagProps {
  tag: string;
  link?: boolean;
  href?: string;
}

const Tag: React.FC<TagProps> = ({ tag, link = false, href }) => {
  const tagContent = (
    <span className="inline-block bg-gray-200 rounded-full px-3 py-1 text-sm font-semibold text-gray-700 mr-2 mb-2 hover:bg-gray-300 transition duration-200">
      #{tag}
    </span>
  );

  if (link && href) {
    return <Link href={href}>{tagContent}</Link>;
  }

  return tagContent;
};

export default Tag;