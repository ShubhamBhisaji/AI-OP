```
import api from './api.js';

export const getProfile = async () => {
  try {
    const response = await api.get('/profile');
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getUser = async () => {
  try {
    const response = await api.get('/user');
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getPosts = async () => {
  try {
    const response = await api.get('/posts');
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const createPost = async (title, content) => {
  try {
    const response = await api.post('/posts', {
      title,
      content,
    });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const updatePost = async (id, title, content) => {
  try {
    const response = await api.put(`/posts/${id}`, {
      title,
      content,
    });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const deletePost = async (id) => {
  try {
    await api.delete(`/posts/${id}`);
    return true;
  } catch (error) {
    throw error;
  }
};

export const getComments = async (postId) => {
  try {
    const response = await api.get(`/comments/${postId}`);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const createComment = async (title, content, postId) => {
  try {
    const response = await api.post(`/comments/${postId}`, {
      title,
      content,
    });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const updateComment = async (id, title, content) => {
  try {
    const response = await api.put(`/comments/${id}`, {
      title,
      content,
    });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const deleteComment = async (id) => {
  try {
    await api.delete(`/comments/${id}`);
    return true;
  } catch (error) {
    throw error;
  }
};
```