/**
 * SUT 接入配置表单（arch/13 §四 sut_configs/，content = sut: 子树，无真凭证）。
 *
 * 覆盖固定字段（基本信息 / configurable / auth）；未知字段不渲染但经 YAML 模式保全。
 * credential_ref 仅为凭证引用名——真值在平台 Secrets（org 级 KV）管理，不入包。
 */
import { Field } from "./Field"
import { AddButton, SectionCard, SectionCardContent, SectionCardHeader, SectionCardTitle } from "../../../components/shared"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Textarea } from "../../../components/shadcn/textarea"

export interface SutLoginTemplate {
  method?: string
  path?: string
  body_template?: string
}
export interface SutAuth {
  type?: string
  credential_ref?: string
  login?: SutLoginTemplate
  extract?: { token_path?: string; token_type?: string }
}
export interface SutConfigData {
  name: string
  channel: string
  base_url: string
  protocol_flavor?: string
  exec_mode?: string
  timeout?: number
  configurable?: Record<string, unknown>
  auth?: SutAuth
  [key: string]: unknown
}

export function SutConfigForm({
  data,
  onChange,
}: {
  data: SutConfigData
  onChange: (d: SutConfigData) => void
}) {
  const patch = (p: Partial<SutConfigData>) => onChange({ ...data, ...p })
  const auth = data.auth ?? {}
  const patchAuth = (p: Partial<SutAuth>) => patch({ auth: { ...auth, ...p } })

  return (
    <div className="space-y-4">
      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle className="text-sm">基本信息</SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent className="grid grid-cols-2 gap-3 p-4">
          <Field label="name（SUT 名称）" required hint="即资产 ID：发布时 asset_id 必须与 name 一致">
            <Input value={data.name ?? ""} onChange={(e) => patch({ name: e.target.value })} />
          </Field>
          <Field label="channel（通道类型）" hint="如 agent_protocol（generic_http / browser 预留）">
            <Input value={data.channel ?? ""} onChange={(e) => patch({ channel: e.target.value })} />
          </Field>
          <div className="col-span-2">
            <Field label="base_url（服务根地址）" required>
              <Input value={data.base_url ?? ""} onChange={(e) => patch({ base_url: e.target.value })} placeholder="https://" />
            </Field>
          </div>
          <Field label="protocol_flavor（协议形态）" hint="commands（线程命令轮询）或 runs（/runs/wait）">
            <Input value={data.protocol_flavor ?? ""} onChange={(e) => patch({ protocol_flavor: e.target.value })} />
          </Field>
          <Field label="exec_mode（执行模式）" hint="wait / background / stream">
            <Input value={data.exec_mode ?? ""} onChange={(e) => patch({ exec_mode: e.target.value })} />
          </Field>
          <Field label="timeout（秒）" optional>
            <Input
              type="number"
              value={data.timeout ?? 300}
              onChange={(e) => patch({ timeout: Number(e.target.value) || undefined })}
            />
          </Field>
        </SectionCardContent>
      </SectionCard>

      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle className="text-sm">configurable（run 请求缺省值）</SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent className="space-y-2 p-4">
          {Object.entries(data.configurable ?? {}).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <Input
                value={k}
                onChange={(e) => {
                  const next = { ...(data.configurable ?? {}) }
                  delete next[k]
                  next[e.target.value] = v
                  patch({ configurable: next })
                }}
              />
              <Input
                value={String(v)}
                onChange={(e) => patch({ configurable: { ...(data.configurable ?? {}), [k]: e.target.value } })}
              />
              <Button size="sm" variant="ghost" onClick={() => {
                const next = { ...(data.configurable ?? {}) }
                delete next[k]
                patch({ configurable: next })
              }}>
                删除
              </Button>
            </div>
          ))}
          <AddButton
            onClick={() => patch({ configurable: { ...(data.configurable ?? {}), "": "" } })}
          >
            添加键值对
          </AddButton>
        </SectionCardContent>
      </SectionCard>

      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle className="text-sm">auth（鉴权）</SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent className="grid grid-cols-2 gap-3 p-4">
          <Field label="type（鉴权类型）" hint="none / static_token / api_login / session_cookie">
            <Input value={auth.type ?? ""} onChange={(e) => patchAuth({ type: e.target.value })} />
          </Field>
          <Field label="credential_ref（凭证引用名）" hint="真凭证存于平台 Secrets（AGENT_EVAL_SUT__<REF>__*），此处仅引用">
            <Input value={auth.credential_ref ?? ""} onChange={(e) => patchAuth({ credential_ref: e.target.value })} />
          </Field>
          <Field label="login.method" optional>
            <Input
              value={auth.login?.method ?? ""}
              onChange={(e) => patchAuth({ login: { ...auth.login, method: e.target.value } })}
            />
          </Field>
          <Field label="login.path（登录接口路径）" optional>
            <Input
              value={auth.login?.path ?? ""}
              onChange={(e) => patchAuth({ login: { ...auth.login, path: e.target.value } })}
            />
          </Field>
          <div className="col-span-2">
            <Field label="login.body_template（登录请求模板）" optional hint="{{ username }} / {{ password }} 由凭证注入">
              <Textarea
                className="min-h-[72px] font-mono text-xs"
                value={auth.login?.body_template ?? ""}
                onChange={(e) => patchAuth({ login: { ...auth.login, body_template: e.target.value } })}
              />
            </Field>
          </div>
          <Field label="extract.token_path" optional hint="从登录响应提取 token 的路径，如 token">
            <Input
              value={auth.extract?.token_path ?? ""}
              onChange={(e) => patchAuth({ extract: { ...auth.extract, token_path: e.target.value } })}
            />
          </Field>
          <Field label="extract.token_type" optional>
            <Input
              value={auth.extract?.token_type ?? ""}
              onChange={(e) => patchAuth({ extract: { ...auth.extract, token_type: e.target.value } })}
            />
          </Field>
        </SectionCardContent>
      </SectionCard>
    </div>
  )
}
