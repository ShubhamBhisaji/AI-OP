import React from 'react';
import { User } from '../../types/user';

type UserTableProps = {
  users: User[];
  onDelete: (userId: string) => void;
  onRoleChange: (userId: string, newRole: 'ADMIN' | 'USER') => void;
};

export const UserTable: React.FC<UserTableProps> = ({ users, onDelete, onRoleChange }) => {
  return (
    <table className="min-w-full table-auto border border-gray-200">
      <thead>
        <tr>
          <th className="px-4 py-2 border-b">Name</th>
          <th className="px-4 py-2 border-b">Email</th>
          <th className="px-4 py-2 border-b">Role</th>
          <th className="px-4 py-2 border-b">Actions</th>
        </tr>
      </thead>
      <tbody>
        {users.map((user) => (
          <tr key={user.id} className="border-t">
            <td className="px-4 py-2">{user.name}</td>
            <td className="px-4 py-2">{user.email}</td>
            <td className="px-4 py-2">
              <select
                value={user.role}
                onChange={(e) =>
                  onRoleChange(user.id, e.target.value as 'ADMIN' | 'USER')
                }
                className="border rounded px-2 py-1"
              >
                <option value="USER">User</option>
                <option value="ADMIN">Admin</option>
              </select>
            </td>
            <td className="px-4 py-2">
              <button
                onClick={() => onDelete(user.id)}
                className="bg-red-500 text-white px-3 py-1 rounded hover:bg-red-600"
              >
                Delete
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};