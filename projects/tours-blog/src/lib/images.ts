import cloudinary from 'cloudinary';

if (!cloudinary.v2) {
  // In case the cloudinary import doesn't have .v2 in dev mode, fallback
  cloudinary.v2 = cloudinary;
}

cloudinary.v2.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET,
});

export const uploadImage = async (filePath: string): Promise<{ url: string; public_id: string }> => {
  try {
    const result = await cloudinary.v2.uploader.upload(filePath, {
      folder: 'tours-blog',
      resource_type: 'image',
    });
    return {
      url: result.secure_url,
      public_id: result.public_id,
    };
  } catch (error) {
    console.error('Error uploading image to Cloudinary:', error);
    throw error;
  }
};

export const deleteImage = async (publicId: string): Promise<void> => {
  try {
    await cloudinary.v2.uploader.destroy(publicId);
  } catch (error) {
    console.error('Error deleting image from Cloudinary:', error);
    throw error;
  }
};

export const getImageUrl = (publicId: string, options?: { width?: number; height?: number; crop?: string }): string => {
  return cloudinary.v2.url(publicId, {
    ...options,
    fetch_format: 'auto',
    quality: 'auto',
  });
};