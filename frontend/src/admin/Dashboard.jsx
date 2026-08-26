import { useState, useEffect } from "react";
import { STAGES, PIPELINE_ID } from "../config";
import { api } from "../api";

export default function Dashboard({ ctx }) {
  const [pipelines, setPipelines] = useState({});
  const [certifiedCount, setCertifiedCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true); setErr(null);
      try {
        // off-chain names
        const { pipelines } = await api.listPipelines().catch(() => ({ pipelines: {} }));
        setPipelines(pipelines || {});

        // on-chain certified count for the default pipeline
        const contracts = await ctx.getReadContracts();
        if (contracts) {
          const hashes = await api.stageHashes(PIPELINE_ID).catch(() => ({ stage_hashes: {} }));
          let count = 0;
          for (const s of STAGES) {
            const h = hashes.stage_hashes?.[s.name];
            if (h) {
              const ok = await contracts.registry.isCertified(PIPELINE_ID, h);
              if (ok) count++;
            }
          }
          setCertifiedCount(count);
        }
      } catch (e) { setErr(e.message); }
      finally { setLoading(false); }
    })();
  }, [ctx]);

  const list = Object.values(pipelines);

  return (
    <div>
      <h1 className="text-2xl font-medium text-gray-900 mb-1">Dashboard</h1>
      <p className="text-sm text-gray-500 mb-6">Overview of pipelines and certification status</p>

      <div className="grid grid-cols-4 gap-4 mb-8">
        <Stat label="Total pipelines" value={list.length || "—"} />
        <Stat label="Default pipeline" value={`#${PIPELINE_ID}`} />
        <Stat label="Stages certified" value={`${certifiedCount} / ${STAGES.length}`} valueClass="text-green-600" />
        <Stat label="Network" value="Amoy" />
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 text-sm font-medium">Pipelines</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-left">
              <th className="font-normal px-5 py-2">ID</th>
              <th className="font-normal px-5 py-2">Name</th>
              <th className="font-normal px-5 py-2">Description</th>
              <th className="font-normal px-5 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id} className="border-t border-gray-100">
                <td className="px-5 py-3">{p.id}</td>
                <td className="px-5 py-3 font-medium">{p.name}</td>
                <td className="px-5 py-3 text-gray-500">{p.description || "—"}</td>
                <td className="px-5 py-3 text-right">
                  <button onClick={() => ctx.goToPipeline(p.id)} className="text-blue-600 hover:underline">View →</button>
                </td>
              </tr>
            ))}
            {!list.length && !loading && (
              <tr><td colSpan="4" className="px-5 py-6 text-center text-gray-400">No pipelines yet. Create one to get started.</td></tr>
            )}
            {loading && <tr><td colSpan="4" className="px-5 py-6 text-center text-gray-400">loading…</td></tr>}
          </tbody>
        </table>
      </div>
      {err && <p className="mt-4 text-sm text-amber-600">Note: {err}</p>}
    </div>
  );
}

function Stat({ label, value, valueClass = "" }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-4">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-2xl font-medium mt-1 ${valueClass}`}>{value}</div>
    </div>
  );
}
