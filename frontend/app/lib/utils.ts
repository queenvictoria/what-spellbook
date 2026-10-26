import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge conditional class names, letting a caller's class win over a component default. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
