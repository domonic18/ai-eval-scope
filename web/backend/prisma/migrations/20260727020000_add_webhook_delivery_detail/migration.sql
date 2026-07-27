-- Webhook 投递详情：记录请求体 + 响应体（便于调试）
ALTER TABLE "webhook_deliveries" ADD COLUMN "request_body" JSONB,
ADD COLUMN "response_body" TEXT;
