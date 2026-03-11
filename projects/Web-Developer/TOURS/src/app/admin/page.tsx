import Link from 'next/link';
import { Button } from '@/components/ui/Button'; // Corrected import path

const AdminDashboard = () => {
  return (
    <div className="container mx-auto p-4">
      <h1 className="text-3xl font-bold mb-6">Admin Dashboard</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-xl font-semibold mb-4">Content Management</h2>
          <p className="text-gray-700 mb-4">Manage blog posts, categories, and tags.</p>
          <Link href="/admin/posts">
            <Button>View Posts</Button>
          </Link>
        </div>

        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-xl font-semibold mb-4">User Management</h2>
          <p className="text-gray-700 mb-4">View and manage registered users.</p>
          <Link href="/admin/users">
            <Button>View Users</Button>
          </Link>
        </div>

        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-xl font-semibold mb-4">Content Moderation</h2>
          <p className="text-gray-700 mb-4">Review reported content.</p>
          <Link href="/admin/moderation">
            <Button>View Reports</Button>
          </Link>
        </div>
      </div>
    </div>
  );
};

export default AdminDashboard;