import { useState, useEffect } from "react";
import { STAGES, PIPELINE_ID, CONTRACTS, AMOY } from "../config";
import { api } from "../api";
import { short, statusStyle } from "../ui";

export default function PipelineView({ ctx }) {
  const [pid, setPid] = useState(ctx.selectedPipeline || PIPELINE_ID);
  const [pipelines, setPipelines] = useState({});
  const [info, setInfo] = useState(null);
  const [stages, setStages] = useState([]);
  const [loading, setLoading] = useState(true);

  // load the pipeline name list for the dropdown
  useEffect(() => {
    api.listPipelines().then((r) => setPipelines(r.pipelines || {})).catch(() => {});
  }, []);

  // keep in sync if another screen changed the selected pipeline
  useEffect(() => { if (ctx.selectedPipeline) setPid(ctx.selectedPipeline); }, [ctx.selectedPipeline]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const p = await api.getPipeline(pid).catch(() => null);
        setInfo(p);

        const contracts = await ctx.getReadContracts();
        const hashes = await api.stageHashes(pid).catch(() => ({ stage_hashes: {} }));

        const out = [];
        const certified = {};
        for (const s of STAGES) {
          const h = hashes.stage_hashes?.[s.name];
          let status = "LOCKED", submitter = null, ts = null;
          if (h && contracts) {
            const ok = await contracts.registry.isCertified(pid, h);
            certified[s.name] = ok;
            if (ok) {
              status = "CERTIFIED";
              try {
                const c = await contracts.registry.getCertificate(pid, h);
                submitter = c.submitter; ts = Number(c.timestamp);
              } catch { /* ignore */ }
            }
          }
          out.push({ ...s, hash: h, status, submitter, ts, certified: !!certified[s.name] });
        }
        for (const st of out) {
          if (st.status !== "CERTIFIED" && st.parents.every((p) => certified[p])) st.status = "READY";
        }
        setStages(out);
      } finally { setLoading(false); }
    })();
  }, [pid, ctx]);

  const list = Object.values(pipelines).sort((a, b) => a.id - b.id);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-sm text-gray-500">Pipeline #{pid}</div>
          <h1 className="text-2xl font-medium text-gray-900">{info?.name || `Pipeline #${pid}`}</h1>
        </div>
        {/* pipeline picker */}
        <select value={pid} onChange={(e) => setPid(Number(e.target.value))}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white">
          {list.length ? list.map((p) => (
            <option key={p.id} value={p.id}>#{p.id} — {p.name}</option>
          )) : <option value={pid}>#{pid}</option>}
        </select>
      </div>

      <div className="text-sm text-gray-500 mb-3">Provenance chain</div>
      <div className="flex gap-3 overflow-x-auto pb-2 mb-8">
        {stages.map((s, i) => (
          <div key={s.name} className="flex items-center">
            <div className={`min-w-[150px] bg-white rounded-xl border ${s.status === "CERTIFIED" ? "border-green-300" : "border-gray-200"} p-4`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">{s.label}</span>
                {s.status === "CERTIFIED" && <span className="text-green-600 text-xs">✓</span>}
              </div>
              <div className={`text-xs ${statusStyle[s.status]}`}>{s.status.toLowerCase()}</div>
              {s.submitter && <div className="text-xs text-gray-400 mt-2">by {short(s.submitter)}</div>}
              {s.ts ? <div className="text-xs text-gray-400">{new Date(s.ts * 1000).toLocaleDateString()}</div> : null}
            </div>
            {i < stages.length - 1 && <span className="text-gray-300 mx-1">→</span>}
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="text-sm font-medium mb-3">Pipeline information</div>
        <div className="grid grid-cols-2 gap-y-2 text-sm">
          <Info label="Pipeline ID" value={pid} />
          <Info label="Stages certified" value={`${stages.filter((s) => s.certified).length} / ${STAGES.length}`} />
          <Info label="Network" value="Polygon Amoy" />
          <Info label="Name" value={info?.name || "—"} />
        </div>
        <div className="mt-4 pt-4 border-t border-gray-100 text-sm">
          <div className="text-gray-500 mb-1">Contract addresses</div>
          <div className="font-mono text-xs text-gray-600">RoleManager: {short(CONTRACTS.roleManager)}</div>
          <div className="font-mono text-xs text-gray-600">Registry V2: {short(CONTRACTS.registry)}</div>
        </div>
        <a href={`${AMOY.explorer}/address/${CONTRACTS.registry}`} target="_blank" rel="noreferrer"
          className="mt-4 inline-block text-sm text-blue-600 hover:underline">View on PolygonScan ↗</a>
      </div>
      {loading && <p className="mt-4 text-sm text-gray-400">loading…</p>}
    </div>
  );
}

function Info({ label, value }) {
  return (<div><span className="text-gray-500">{label}: </span><span className="text-gray-900">{value}</span></div>);
}