import { useState, useEffect } from "react";
import { ethers } from "ethers";
import { STAGES, PIPELINE_ID, CONTRACTS } from "../config";
import { api } from "../api";
import PipelinePicker from "./PipelinePicker";

// DAG node centres (SVG coordinate space, viewBox 0 0 620 610)
const POS = {
  dataset:     { x: 155, y: 90  },
  environment: { x: 465, y: 90  },
  cleaning:    { x: 155, y: 270 },
  training:    { x: 310, y: 420 },
  model:       { x: 310, y: 555 },
};

const EDGES = [
  { from: "dataset",     to: "cleaning"  },
  { from: "environment", to: "cleaning"  },
  { from: "environment", to: "training"  },
  { from: "cleaning",    to: "training"  },
  { from: "training",    to: "model"     },
];

const R = 56;

// Priority: chain broken > upstream compromised > role violated > ok > not certified
function nodeStyle(s) {
  if (!s.certified)             return { fill: "#f3f4f6", stroke: "#d1d5db", labelColor: "#9ca3af", statusColor: "#9ca3af" };
  if (s.chainOk === false)      return { fill: "#fef2f2", stroke: "#f87171", labelColor: "#1f2937", statusColor: "#dc2626" };
  if (s.upstreamBroken)         return { fill: "#fff1f1", stroke: "#fca5a5", labelColor: "#1f2937", statusColor: "#dc2626" };
  if (s.roleOk  === false)      return { fill: "#fffbeb", stroke: "#fbbf24", labelColor: "#1f2937", statusColor: "#b45309" };
  return                               { fill: "#f0fdf4", stroke: "#4ade80", labelColor: "#1f2937", statusColor: "#16a34a" };
}

function nodeIcon(s) {
  if (!s.certified)             return { icon: "○", color: "#9ca3af" };
  if (s.chainOk === false)      return { icon: "✗", color: "#dc2626" };
  if (s.upstreamBroken)         return { icon: "✗", color: "#dc2626" };
  if (s.roleOk  === false)      return { icon: "!", color: "#d97706" };
  return                               { icon: "✓", color: "#16a34a" };
}

function nodeStatus(s) {
  if (!s.certified)             return "not certified";
  if (s.chainOk === false)      return "chain broken";
  if (s.upstreamBroken)         return "upstream compromised";
  if (s.roleOk  === false)      return "role violation";
  return "all ok";
}

function edgeColor(fromStage, toStage, stageHashes) {
  if (!toStage?.certified || !toStage?.onChainParents) return "#d1d5db";
  // if source is compromised in any way, the edge going out is red
  if (fromStage?.chainOk === false || fromStage?.upstreamBroken || fromStage?.roleOk === false || !fromStage?.certified)
    return "#f87171";
  const raw = stageHashes[fromStage?.name] || "";
  const exp = (raw.startsWith("0x") ? raw : "0x" + raw).toLowerCase();
  return toStage.onChainParents.includes(exp) ? "#4ade80" : "#f87171";
}

function short(addr) {
  return addr ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : "";
}

function Arrow({ from, to, color }) {
  const dx = to.x - from.x, dy = to.y - from.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  const ux = dx / len, uy = dy / len;
  const x1 = from.x + ux * R, y1 = from.y + uy * R;
  const x2 = to.x   - ux * R, y2 = to.y   - uy * R;
  const mid = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
  const cx = mid.x - uy * 18, cy = mid.y + ux * 18;
  const markerId = `arr-${color.replace("#", "")}`;
  return (
    <g>
      <defs>
        <marker id={markerId} markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L7,3 z" fill={color} />
        </marker>
      </defs>
      <path d={`M${x1},${y1} Q${cx},${cy} ${x2},${y2}`}
        stroke={color} strokeWidth="2.5" fill="none"
        strokeDasharray={color === "#d1d5db" ? "6 4" : "none"}
        markerEnd={`url(#${markerId})`} />
    </g>
  );
}

function Node({ stage, x, y }) {
  const st = nodeStyle(stage);
  const { icon, color: iconColor } = nodeIcon(stage);
  const status = nodeStatus(stage);
  const lines = stage.label.split(" ");

  return (
    <g>
      <circle cx={x} cy={y} r={R} fill={st.fill} stroke={st.stroke} strokeWidth="2.5" />

      {/* main icon */}
      <text x={x} y={y - 20} textAnchor="middle" fontSize="16" fill={iconColor} fontWeight="bold">{icon}</text>

      {/* stage label — split on space if needed */}
      {lines.length === 1
        ? <text x={x} y={y + 2} textAnchor="middle" fontSize="12" fontWeight="600" fill={st.labelColor}>{lines[0]}</text>
        : lines.map((l, i) => (
          <text key={i} x={x} y={y - 4 + i * 15} textAnchor="middle" fontSize="11" fontWeight="600" fill={st.labelColor}>{l}</text>
        ))
      }

      {/* status */}
      <text x={x} y={y + 20} textAnchor="middle" fontSize="9" fill={st.statusColor} fontWeight="600">
        {status}
      </text>

      {/* submitter address (small, below status) */}
      {stage.submitter && (
        <text x={x} y={y + 33} textAnchor="middle" fontSize="8" fill="#9ca3af">{short(stage.submitter)}</text>
      )}

      {/* role badge — small shield icon top-right of node for role-gated stages */}
      {stage.requiredRole && stage.certified && (
        <g transform={`translate(${x + 36}, ${y - 46})`}>
          <circle r="11" fill={stage.roleOk === false ? "#fef3c7" : "#f0fdf4"}
            stroke={stage.roleOk === false ? "#fbbf24" : "#4ade80"} strokeWidth="1.5" />
          <text textAnchor="middle" y="4" fontSize="10">
            {stage.roleOk === false ? "⚠" : "🔑"}
          </text>
        </g>
      )}
    </g>
  );
}

export default function ChainAudit({ ctx }) {
  const pid = ctx.selectedPipeline;
  const [stages, setStages] = useState([]);
  const [stageHashes, setStageHashes] = useState({});
  const [pipelineName, setPipelineName] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const pInfo = await api.getPipeline(pid).catch(() => null);
        setPipelineName(pInfo?.name || `Pipeline #${pid}`);
        const contracts = await ctx.getReadContracts();
        const hashes = await api.stageHashes(pid).catch(() => ({ stage_hashes: {} }));
        const sh = hashes.stage_hashes || {};
        setStageHashes(sh);

        const out = [];
        const certified = {};

        for (const s of STAGES) {
          const h = sh[s.name];
          let certifiedFlag = false, onChainParents = null, submitter = null, ts = null;
          if (h && contracts) {
            try {
              const ok = await contracts.registry.isCertified(pid, h);
              certifiedFlag = ok;
              certified[s.name] = ok;
              if (ok) {
                try {
                  const c = await contracts.registry.getCertificate(pid, h);
                  submitter = c.submitter;
                  ts = Number(c.timestamp);
                  onChainParents = Array.from(c.parents).map((p) => p.toLowerCase());
                } catch { /* ignore */ }
              }
            } catch { certified[s.name] = false; }
          }

          // chain integrity check
          let chainOk = null;
          if (certifiedFlag && s.parents.length > 0 && onChainParents) {
            const expectedHashes = s.parents.map((p) => {
              const raw = sh[p] || "";
              return (raw.startsWith("0x") ? raw : "0x" + raw).toLowerCase();
            });
            chainOk = expectedHashes.every((exp) => onChainParents.includes(exp));
          } else if (certifiedFlag) {
            chainOk = true;
          }

          // role verification check
          let roleOk = null;
          if (certifiedFlag && submitter && s.requiredRole && contracts) {
            try {
              const roleHash = ethers.id(s.requiredRole); // keccak256(roleName)
              roleOk = await contracts.roleManager.hasRole(pid, roleHash, submitter);
            } catch { roleOk = null; }
          } else if (certifiedFlag && !s.requiredRole) {
            roleOk = true; // root stages — no role required
          }

          out.push({ ...s, hash: h, certified: certifiedFlag, onChainParents, chainOk, roleOk, submitter, ts, upstreamBroken: false });
        }

        // propagate broken status downstream (topological order = STAGES order)
        const compromised = new Set(
          out.filter((s) => !s.certified || s.chainOk === false || s.roleOk === false).map((s) => s.name)
        );
        for (const s of out) {
          if (!compromised.has(s.name) && s.parents.some((p) => compromised.has(p))) {
            s.upstreamBroken = true;
            compromised.add(s.name);
          }
        }

        setStages(out);
      } finally { setLoading(false); }
    })();
  }, [pid, ctx]);

  const stageMap = Object.fromEntries(stages.map((s) => [s.name, s]));
  const certifiedCount = stages.filter((s) => s.certified).length;
  // ── export helpers ──────────────────────────────────────────────────────────
  function buildReportData() {
    const verdict = allIssues();
    return {
      report: {
        generated_at: new Date().toISOString(),
        pipeline_id: pid,
        pipeline_name: pipelineName,
        network: "Polygon Amoy",
        registry_contract: CONTRACTS.registry,
        chain_verdict: verdict,
        stages_certified: stages.filter((s) => s.certified).length,
        stages_total: stages.length,
      },
      stages: stages.map((s) => ({
        name: s.name,
        label: s.label,
        required_role: s.requiredRole || null,
        manifest_hash: s.hash || null,
        certified: s.certified,
        submitter: s.submitter || null,
        timestamp: s.ts ? new Date(s.ts * 1000).toISOString() : null,
        parents: s.parents,
        on_chain_parents: s.onChainParents || [],
        chain_integrity: !s.certified ? "not_certified"
          : s.chainOk === false ? "broken"
          : s.upstreamBroken ? "upstream_compromised"
          : "ok",
        role_check: !s.certified ? "not_applicable"
          : !s.requiredRole ? "not_required"
          : s.roleOk === true ? "ok"
          : s.roleOk === false ? "violated"
          : "unknown",
      })),
      issues: [
        ...stages.filter((s) => s.chainOk === false).map((s) => ({
          stage: s.name, type: "chain_broken",
          detail: `Parent hash mismatch. On-chain parents: [${(s.onChainParents || []).join(", ")}]`,
        })),
        ...stages.filter((s) => s.upstreamBroken).map((s) => ({
          stage: s.name, type: "upstream_compromised",
          detail: `Depends on a compromised parent stage: ${s.parents.join(", ")}`,
        })),
        ...stages.filter((s) => s.roleOk === false).map((s) => ({
          stage: s.name, type: "role_violation",
          detail: `Stage signed by ${s.submitter} who does not hold role ${s.requiredRole}`,
        })),
      ],
    };
  }

  function downloadJSON() {
    const data = buildReportData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `provenance_report_pipeline_${pid}.json`; a.click();
    URL.revokeObjectURL(url);
  }

  function printReport() {
    const data = buildReportData();
    const stageRows = data.stages.map((s) => `
      <tr>
        <td>${s.label}</td>
        <td class="mono">${s.manifest_hash ? s.manifest_hash.slice(0, 20) + "…" : "—"}</td>
        <td class="mono">${s.submitter ? s.submitter.slice(0, 10) + "…" : "—"}</td>
        <td>${s.timestamp ? new Date(s.timestamp).toLocaleString() : "—"}</td>
        <td>${s.required_role || "none"}</td>
        <td class="status ${s.chain_integrity}">${s.chain_integrity.replace("_", " ")}</td>
        <td class="status ${s.role_check}">${s.role_check.replace("_", " ")}</td>
      </tr>`).join("");

    const issueRows = data.issues.length
      ? data.issues.map((i) => `<tr><td>${i.stage}</td><td>${i.type.replace("_", " ")}</td><td>${i.detail}</td></tr>`).join("")
      : `<tr><td colspan="3" style="text-align:center;color:#16a34a">No issues found</td></tr>`;

    const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
    <title>Provenance Report — ${data.report.pipeline_name}</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 40px; color: #111; font-size: 13px; }
      h1 { font-size: 22px; margin-bottom: 4px; }
      .meta { color: #555; margin-bottom: 24px; font-size: 12px; }
      .verdict { display:inline-block; padding: 4px 14px; border-radius: 20px; font-weight: 600; font-size: 13px; margin-bottom: 28px; }
      .VALID { background:#dcfce7; color:#15803d; }
      .BROKEN { background:#fee2e2; color:#dc2626; }
      .ROLE_VIOLATION { background:#fef9c3; color:#854d0e; }
      h2 { font-size: 15px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; margin-top: 32px; }
      table { width:100%; border-collapse: collapse; margin-top: 10px; }
      th { background:#f9fafb; text-align:left; padding: 7px 10px; font-size:11px; color:#6b7280; border-bottom:1px solid #e5e7eb; }
      td { padding: 7px 10px; border-bottom: 1px solid #f3f4f6; vertical-align:top; }
      .mono { font-family: monospace; font-size: 11px; }
      .status { font-weight: 600; text-transform: capitalize; }
      .ok, .not_required { color: #16a34a; }
      .broken, .violated, .upstream_compromised { color: #dc2626; }
      .not_certified, .not_applicable, .unknown { color: #9ca3af; }
      .footer { margin-top: 40px; font-size: 11px; color: #9ca3af; border-top: 1px solid #e5e7eb; padding-top: 12px; }
      @media print { body { margin: 20px; } }
    </style></head><body>
    <h1>Provenance Report</h1>
    <div class="meta">
      Pipeline #${data.report.pipeline_id} &nbsp;·&nbsp; ${data.report.pipeline_name}
      &nbsp;·&nbsp; Network: ${data.report.network}
      &nbsp;·&nbsp; Generated: ${new Date(data.report.generated_at).toLocaleString()}
    </div>
    <div>
      <span class="verdict ${data.report.chain_verdict}">
        ${data.report.chain_verdict === "VALID" ? "✓ Chain Verified" : "✗ " + data.report.chain_verdict.replace("_", " ")}
      </span>
    </div>
    <div class="meta">Stages certified: ${data.report.stages_certified} / ${data.report.stages_total}
      &nbsp;·&nbsp; Registry: <span style="font-family:monospace">${data.report.registry_contract}</span>
    </div>
    <h2>Stage Details</h2>
    <table>
      <thead><tr>
        <th>Stage</th><th>Manifest Hash</th><th>Submitter</th>
        <th>Timestamp</th><th>Required Role</th><th>Chain</th><th>Role</th>
      </tr></thead>
      <tbody>${stageRows}</tbody>
    </table>
    <h2>Issues</h2>
    <table>
      <thead><tr><th>Stage</th><th>Type</th><th>Detail</th></tr></thead>
      <tbody>${issueRows}</tbody>
    </table>
    <div class="footer">
      Blockchain-Certified ML Pipeline · Polygon Amoy Testnet ·
      Registry contract: ${data.report.registry_contract}
    </div>
    <script>window.onload = () => window.print();</script>
    </body></html>`;

    const w = window.open("", "_blank");
    w.document.write(html);
    w.document.close();
  }

  function allIssues() {
    if (stages.some((s) => s.chainOk === false || s.upstreamBroken)) return "BROKEN";
    if (stages.some((s) => s.roleOk === false)) return "ROLE_VIOLATION";
    if (stages.every((s) => s.certified)) return "VALID";
    return "INCOMPLETE";
  }
  // ────────────────────────────────────────────────────────────────────────────

  const chainBroken      = stages.filter((s) => s.chainOk === false);
  const upstreamBroken   = stages.filter((s) => s.upstreamBroken);
  const roleViolations   = stages.filter((s) => s.roleOk === false);
  const anyBroken        = chainBroken.length > 0 || upstreamBroken.length > 0 || roleViolations.length > 0;
  const allOk            = certifiedCount > 0 && !anyBroken;

  const bannerColor = allOk ? "bg-green-50 border-green-200 text-green-700"
    : roleViolations.length > 0 && !chainBroken.length && !upstreamBroken.length
      ? "bg-amber-50 border-amber-200 text-amber-700"
      : "bg-red-50 border-red-200 text-red-700";

  const bannerText = allOk
    ? `Chain integrity and role authorisation verified — all ${certifiedCount} stage(s) are valid.`
    : [
        chainBroken.length    > 0 && `Hash mismatch in: ${chainBroken.map((s) => s.label).join(", ")}.`,
        upstreamBroken.length > 0 && `Upstream compromised — affected: ${upstreamBroken.map((s) => s.label).join(", ")}.`,
        roleViolations.length > 0 && `Role violation in: ${roleViolations.map((s) => s.label).join(", ")}.`,
      ].filter(Boolean).join("  ");

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium text-gray-900 mb-1">Chain Audit</h1>
          <p className="text-sm text-gray-500">Pipeline #{pid} · provenance graph + role verification</p>
        </div>
        <div className="flex items-center gap-2">
          {!loading && stages.some((s) => s.certified) && (<>
            <button onClick={downloadJSON}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 transition">
              Download JSON
            </button>
            <button onClick={printReport}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 transition">
              Export PDF
            </button>
          </>)}
          <PipelinePicker ctx={ctx} />
        </div>
      </div>

      {/* overall banner */}
      {!loading && certifiedCount > 0 && (
        <div className={`mb-5 rounded-lg px-4 py-3 text-sm border ${bannerColor}`}>
          {bannerText}
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-4 mb-4">
        {[
          { stroke: "#4ade80", fill: "#f0fdf4", label: "Verified — hash ok + role ok" },
          { stroke: "#f87171", fill: "#fef2f2", label: "Chain broken — parent hash mismatch" },
          { stroke: "#fbbf24", fill: "#fffbeb", label: "Role violation — wrong signer" },
          { stroke: "#d1d5db", fill: "#f3f4f6", label: "Not certified yet" },
        ].map(({ stroke, fill, label }) => (
          <div key={label} className="flex items-center gap-2 text-sm text-gray-600">
            <svg width="16" height="16">
              <circle cx="8" cy="8" r="7" fill={fill} stroke={stroke} strokeWidth="2" />
            </svg>
            {label}
          </div>
        ))}
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <span className="text-base">🔑</span> Role-gated stage badge
        </div>
      </div>

      {/* DAG */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 mb-5">
        {loading ? (
          <p className="text-sm text-gray-400 text-center py-16">Loading chain data…</p>
        ) : (
          <svg viewBox="0 0 620 620" className="w-full max-h-[560px]">
            {/* edges */}
            {EDGES.map((e) => (
              <Arrow key={`${e.from}-${e.to}`}
                from={POS[e.from]} to={POS[e.to]}
                color={edgeColor(stageMap[e.from], stageMap[e.to], stageHashes)} />
            ))}

            {/* nodes */}
            {stages.map((s) => (
              <Node key={s.name} stage={s} x={POS[s.name].x} y={POS[s.name].y} />
            ))}
          </svg>
        )}
      </div>

      {/* detail panels */}
      {(chainBroken.length > 0 || roleViolations.length > 0) && (
        <div className="space-y-4">

          {/* hash mismatch detail */}
          {chainBroken.length > 0 && (
            <div className="bg-white rounded-xl border border-red-200 p-5">
              <div className="text-sm font-medium text-red-700 mb-3">Parent hash mismatch detail</div>
              {chainBroken.map((s) => (
                <div key={s.name} className="mb-4 last:mb-0">
                  <div className="text-sm font-medium text-gray-800 mb-2">{s.label}</div>
                  <table className="w-full text-xs font-mono border-collapse">
                    <thead>
                      <tr className="text-left text-gray-500">
                        <th className="pr-4 pb-1 font-sans font-medium">Parent stage</th>
                        <th className="pr-4 pb-1 font-sans font-medium">Expected (local store)</th>
                        <th className="pb-1 font-sans font-medium">On-chain in certificate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.parents.map((p) => {
                        const raw = stageHashes[p] || "";
                        const exp = (raw.startsWith("0x") ? raw : "0x" + raw).toLowerCase();
                        const found = s.onChainParents?.includes(exp);
                        return (
                          <tr key={p} className={found ? "text-green-700" : "text-red-600"}>
                            <td className="pr-4 py-1 font-sans">{p}</td>
                            <td className="pr-4 py-1 break-all">{exp || "—"}</td>
                            <td className="py-1 font-sans">{found ? "✓ matches" : "✗ not found"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}

          {/* role violation detail */}
          {roleViolations.length > 0 && (
            <div className="bg-white rounded-xl border border-amber-200 p-5">
              <div className="text-sm font-medium text-amber-700 mb-3">Role violation detail</div>
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left text-gray-500 text-xs">
                    <th className="pr-4 pb-2 font-medium">Stage</th>
                    <th className="pr-4 pb-2 font-medium">Required role</th>
                    <th className="pr-4 pb-2 font-medium">Signed by</th>
                    <th className="pb-2 font-medium">Has role?</th>
                  </tr>
                </thead>
                <tbody>
                  {roleViolations.map((s) => (
                    <tr key={s.name} className="text-red-600">
                      <td className="pr-4 py-1">{s.label}</td>
                      <td className="pr-4 py-1 font-mono text-xs">{s.requiredRole}</td>
                      <td className="pr-4 py-1 font-mono text-xs">{s.submitter || "—"}</td>
                      <td className="py-1">✗ No</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {!loading && certifiedCount === 0 && (
        <p className="text-sm text-gray-400 text-center mt-8">No stages certified yet for this pipeline.</p>
      )}
    </div>
  );
}
