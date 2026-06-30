import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/** 合并 className（clsx + tailwind-merge 去重冲突）。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
