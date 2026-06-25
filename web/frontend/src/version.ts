/** 应用版本号：构建期由 Vite define 注入（详见 vite.config.ts）；未注入时回退到 1.0.0。 */
export const APP_VERSION: string = import.meta.env.VITE_APP_VERSION || "1.0.0"
