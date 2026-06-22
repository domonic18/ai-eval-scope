import crypto from "crypto"

/**
 * 将任意字符串转为 URL-safe slug（小写、连字符、去重）。
 * 中文等非 ASCII 保留（不做音译），仅去控制符与空白。
 */
export function slugify(input: unknown): string {
  return String(input ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/[^\w\-.]+/g, "")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
}

/** 确保唯一：拼接随机短后缀。 */
export function uniquify(slug: string): string {
  return `${slug}-${crypto.randomBytes(3).toString("hex")}`
}
