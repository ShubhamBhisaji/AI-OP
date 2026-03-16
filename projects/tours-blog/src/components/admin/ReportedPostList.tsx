import React from 'react';
import { Post } from '@/types/post';
import { Button } from '@/components/ui/Button/Button';

interface ReportedPostListProps {
  reportedPosts: Post[];
  onResolve: (postId: string) => void;
  onDelete: (postId: string) => void;
}

const ReportedPostList: React.FC<ReportedPostListProps> = ({ reportedPosts, onResolve, onDelete }) => {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Title
            </th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Reported By
            </th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Report Reason
            </th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {reportedPosts.map((post) => (
            <tr key={post.id}>
              <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                {post.title}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                {/* This would ideally come from a user object if available on the report */}
                Anonymous User
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                {/* This would ideally come from a report object */}
                Inappropriate Content
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                <Button onClick={() => onResolve(post.id)} className="mr-2">Resolve</Button>
                <Button onClick={() => onDelete(post.id)} variant="destructive">Delete</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default ReportedPostList;