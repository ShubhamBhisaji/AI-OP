'use client';

import { useState, useEffect } from 'react';
import { Button, Card, Input } from '@/components/ui';
import { UserTable } from '@/components/admin/UserTable';
import { fetchUsers, deleteUser, updateUserRole } from '@/lib/admin';
import { User } from '@/types/user';

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadUsers = async () => {
      try {
        setLoading(true);
        const fetchedUsers = await fetchUsers();
        setUsers(fetchedUsers);
      } catch (err) {
        setError('Failed to load users.');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    loadUsers();
  }, []);

  const handleDeleteUser = async (userId: string) => {
    if (window.confirm('Are you sure you want to delete this user? This action cannot be undone.')) {
      try {
        await deleteUser(userId);
        setUsers(users.filter(user => user.id !== userId));
      } catch (err) {
        setError('Failed to delete user.');
        console.error(err);
      }
    }
  };

  const handleUpdateRole = async (userId: string, newRole: 'ADMIN' | 'USER') => {
    try {
      await updateUserRole(userId, newRole);
      setUsers(users.map(user => (user.id === userId ? { ...user, role: newRole } : user)));
    } catch (err) {
      setError(`Failed to update role for user ${userId}.`);
      console.error(err);
    }
  };

  const filteredUsers = users.filter(user =>
    user.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    user.email.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-3xl font-bold mb-6">Manage Users</h1>

      <Card className="mb-6 p-4">
        <Input
          type="text"
          placeholder="Search by name or email..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full"
        />
      </Card>

      {loading && <p>Loading users...</p>}
      {error && <p className="text-red-500">{error}</p>}

      {!loading && !error && (
        <Card>
          <UserTable
            users={filteredUsers}
            onDelete={handleDeleteUser}
            onRoleChange={handleUpdateRole}
          />
        </Card>
      )}
    </div>
  );
}