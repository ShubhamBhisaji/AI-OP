import { type ClassValue } from "clsx";
import clsx from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Safely merges and CSS class names.
 * @param inputs - An array of class names or conditions.
 * @returns A single string of merged and cleaned class names.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(...inputs));
}

/**
 * Capitalizes the first letter of a string.
 * @param str - The input string.
 * @returns The capitalized string.
 */
export function capitalizeFirstLetter(str: string): string {
  if (!str) return "";
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Formats a date into a human-readable string (e.g., "January 1, 2023").
 * @param date - The date to format.
 * @returns The formatted date string.
 */
export function formatDate(date: Date | string): string {
  const options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "long",
    day: "numeric",
  };
  return new Date(date).toLocaleDateString(undefined, options);
}

/**
 * Generates a slug from a given string.
 * This is a basic implementation and can be extended for more robust slug generation.
 * @param text - The input string.
 * @returns A URL-friendly slug.
 */
export function generateSlug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "") // Remove invalid characters
    .trim()
    .replace(/\s+/g, "-"); // Replace spaces with hyphens
}

/**
 * Checks if the current environment is production.
 * @returns True if in production, false otherwise.
 */
export function isProduction(): boolean {
  return process.env.NODE_ENV === "production";
}

/**
 * Extracts the domain from a URL.
 * @param url - The input URL.
 * @returns The domain name.
 */
export function getDomainFromUrl(url: string): string {
  try {
    const urlObject = new URL(url);
    return urlObject.hostname;
  } catch (error) {
    console.error("Invalid URL provided:", url, error);
    return "";
  }
}