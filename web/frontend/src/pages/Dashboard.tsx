import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardProject, TrendPoint } from "../types";
import { fmt3, num, timeAgo } from "../lib/format";
import {
  Badge,
  Button,
  Empty,
  Field,
  Input,
  Modal,
  Skeleton,
  Sparkline,
  useCrumbs,
  useOrg,
  useToast,
} from "../components/ui";
import { IconPlus, IconRefresh } from "../components/icons";

function projectHealth(p: DashboardProject): { variant: "success" | "warning" | "neutral"; label: string; dot: string; sparkColor: string } {
  if (!p.latestRun) return { variant: "neutral", label: "未运行", dot: "var(--text-tertiary)", sparkColor: "var(--text-tertiary)" };
  const dr = p.latestRun.dr;
  if (dr == null) return { variant: "neutral", label: "未运行", dot: "var(--text-tertiary)", sparkColor: "var(--signal)" };
  if (dr >= 0.95) return { variant: "success", label: "健康", dot: "var(--success)", sparkColor: "var(--signal)" };
  if (dr >= 0.9) return { variant: "warning", label: "关注", dot: "var(--warning)", sparkColor: "var(--warning)" };
  return { variant: "warning", label: "关注", dot: "var(--warning)", sparkColor: "var(--warning)" };
}

export default function Dashboard() {
  const { activeOrg } = useOrg();
  const { setCrumbs } = useCrumbs();
  const toast = useToast();
  const nav = useNavigate();
  const [projects, setProjects] = useState<DashboardProject[] | null>(null);
  const [sparks, setSparks] = useState<Record<string, number[]>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    setCrumbs([{ label: "项目看板" }]);
  }, [setCrumbs]);

  async function load() {
    if (!activeOrg) {
      setProjects([]);
      return;
    }
    setProjects(null);
    setSparks({});
    try {
      const ps: DashboardProject[] = await api.dashboard(activeOrg);
      setProjects(ps);
      const entries = await Promise.all(
        ps.map(async (p: DashboardProject): Promise<[string, number[]]> => {
          try {
            const t: TrendPoint[] = await api.projectTrends(p.id, 8);
            return [p.id, t.map((x: TrendPoint) => x.DR).filter((v): v is number => v != null)];
          } catch {
            return [p.id, []];
          }
        })
      );
      setSparks(Object.fromEntries(entries));
    } catch {
      setProjects([]);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOrg]);

  async function doCreate() {
    if (!activeOrg || !name.trim() || !slug.trim()) {
      toast.error("请填写项目名称与 Slug");
      return;
    }
    if (!/^[a-z0-9][a-z0-9-]*$/.test(slug.trim())) {
      toast.error("Slug 仅允许小写字母、数字与连字符");
      return;
    }
    setCreating(true);
    try {
      const p = await api.createProject(activeOrg, name.trim(), slug.trim());
      toast.success("项目已创建");
      setCreateOpen(false);
      setName("");
      setSlug("");
      nav(`/project/${p.id}`);
    } catch (e) {
      toast.error("创建失败：" + ((e as Error).message ?? ""));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>项目看板</h1>
          <div className="sub">组织内全部评估项目</div>
        </div>
        <div className="page-actions">
          <Button icon={<IconRefresh size={15} />} onClick={load}>
            刷新
          </Button>
          <Button variant="primary" icon={<IconPlus size={15} />} onClick={() => setCreateOpen(true)}>
            新建项目
          </Button>
        </div>
      </div>

      {projects === null ? (
        <div className="proj-grid r-2">
          {[0, 1, 2].map((i) => (
            <div className="card pc" key={i}>
              <Skeleton height={18} width="60%" />
              <div style={{ height: 28, margin: "14px 0" }}>
                <Skeleton height={28} />
              </div>
              <Skeleton height={18} />
            </div>
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="card r-2">
          <div className="card-body">
            <Empty title="该组织下暂无项目" children={<>点击右上角「新建项目」创建第一个评估项目。</>} />
          </div>
        </div>
      ) : (
        <div className="proj-grid r-2">
          {projects.map((p) => {
            const h = projectHealth(p);
            const drVal = p.latestRun?.dr;
            const drColor = drVal == null ? "var(--text-tertiary)" : drVal >= 0.95 ? "var(--success)" : "var(--warning)";
            return (
              <Link key={p.id} to={`/project/${p.id}`} className={`card-link pc ${!p.latestRun ? "" : ""}`} style={!p.latestRun ? { opacity: 0.75 } : undefined}>
                <div className="pc-head">
                  <div>
                    <div className="pc-name">{p.name}</div>
                    <div className="pc-slug">{p.slug}</div>
                  </div>
                  <Badge variant={h.variant} dot={h.dot}>
                    {h.label}
                  </Badge>
                </div>

                {(sparks[p.id]?.length ?? 0) > 1 ? (
                  <Sparkline data={sparks[p.id]} color={h.sparkColor} />
                ) : (
                  <div style={{ height: 28, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-quaternary)", fontSize: 11 }}>
                    {p.latestRun ? "暂无趋势数据" : ""}
                  </div>
                )}

                <div className="pc-stats">
                  <div>
                    <div className="pc-stat-val" style={{ color: drColor }}>
                      {fmt3(p.latestRun?.dr)}
                    </div>
                    <div className="pc-stat-lab">最新 DR</div>
                  </div>
                  <div>
                    <div className="pc-stat-val">{fmt3(p.latestRun?.avgReward)}</div>
                    <div className="pc-stat-lab">Reward</div>
                  </div>
                  <div>
                    <div className="pc-stat-val">{num(p.runCount)}</div>
                    <div className="pc-stat-lab">运行数</div>
                  </div>
                </div>

                <div className="pc-foot">
                  <span>{p.latestRun ? `最近运行 ${timeAgo(p.latestRun.createdAt)}` : "等待首个运行接入"}</span>
                  {p.latestRun && <span className="mono">#{p.latestRun.runId.slice(-8)}</span>}
                </div>
              </Link>
            );
          })}

          {/* 新建项目虚线块 */}
          <button className="card-link pc-new" onClick={() => setCreateOpen(true)}>
            <IconPlus size={28} />
            <span style={{ fontSize: 13, fontWeight: 550 }}>新建项目</span>
          </button>
        </div>
      )}

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="新建项目"
        desc="项目是评估数据的容器，对应一类被测 Agent"
        footer={
          <>
            <Button onClick={() => setCreateOpen(false)}>取消</Button>
            <Button variant="primary" onClick={doCreate} disabled={creating}>
              {creating ? "创建中…" : "创建并配置接入"}
            </Button>
          </>
        }
      >
        <Field label="项目名称">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：课件生成评估" autoFocus />
        </Field>
        <Field label="Slug（组织内唯一）" help="用于接入标识与 URL，仅小写字母、数字、连字符" style={{ marginBottom: 0 }}>
          <Input className="mono" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="courseware" />
        </Field>
      </Modal>
    </div>
  );
}
