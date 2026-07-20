/** 共享的 async route wrapper：捕获 Promise rejection → next(err)。
 *  消除各路由文件中重复定义的 wrap 局部函数。 */
import type { RequestHandler } from "express"

export function wrap(fn: RequestHandler): RequestHandler {
  return (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next)
}
