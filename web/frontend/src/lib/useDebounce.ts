import { useEffect, useState } from "react"

/**
 * 防抖值：value 变化后 delay ms 内无新变化才更新返回值。
 * 用于搜索框"输入即查"，避免每次按键都发请求。
 */
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}
