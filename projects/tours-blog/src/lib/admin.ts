import { User } from '../types/user';

// Dummy backend simulation
export async function fetchUsers(): Promise<User[]> {
  // In a real app this would be a fetch or axios to an API endpoint.
  return [
    { id: '1', name: 'Alice', email: 'alice@example.com', role: 'ADMIN' },
    { id: '2', name: 'Bob', email: 'bob@example.com', role: 'USER' }
  ];
}

export async function deleteUser(userId: string): Promise<void> {
  // In a real app this would call an API.
  return;
}

export async function updateUserRole(userId: string, newRole: 'ADMIN' | 'USER'): Promise<void> {
  // In a real app this would call an API.
  return;
}