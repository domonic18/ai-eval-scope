-- Add platform-level role + status to users (super-admin backend)
-- role:   user | admin   (admin = super-admin, cross-tenant mgmt; first registered user auto-admin at app layer)
-- status: active | disabled (disabled → login/auth rejected)

ALTER TABLE "users"
    ADD COLUMN "role"   TEXT NOT NULL DEFAULT 'user',
    ADD COLUMN "status" TEXT NOT NULL DEFAULT 'active';
