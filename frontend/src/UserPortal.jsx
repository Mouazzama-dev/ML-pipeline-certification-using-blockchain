import { useState, useEffect } from "react";
import { AMOY, STAGES, PIPELINE_ID } from "./config";
import { usePipeline } from "./usePipeline";
import { api } from "./api";
import { amoyTxOpts } from "./txopts";
import { short, statusStyle } from "./ui";

// User portal: pick a pipeline, see the chain with your stage highlighted,
// upload your output and certify it. Role is checked per selected pipeline.
export default function UserPortal({ address, getReadContracts, getWriteContracts }) {
  const [pid, setPid] = useState(PIPELINE_ID);
  const [pipelines, setPipelines] = useState({});
  const [actorStages, setActorStages] = useState([]);
  const [role, setRole] = useState(null);
  const [checking, setChecking] = useState(true);

  const { stages, loading, refresh } = usePipeline(getReadContracts, address, pid);

  // load pipeline names for the dropdown
  useEffect(() => {
    api.listPipelines().then((r) => setPipelines(r.pipelines || {})).catch(() => {});
  }, []);

  // re-check this wallet's role/stages on the SELECTED pipeline
  useEffect(() => {
    (async () => {
      setChecking(true);
      try {
        const contracts = await getReadContracts();
        if (!contracts) return;
        const gated = STAGES.filter((s) => s.requiredRole);
        const results = await Promise.all(
          gated.map((s) => contracts.roleManager.canCertify(pid, s.name, address))
        );
        const mine = gated.filter((_, i) => results[i]).map((s) => s.name);
        setActorStages(mine);
        setRole(mine.length ? STAGES.find((s) => s.name === mine[0]).requiredRole : null);
      } catch {
        setActorStages([]); setRole(null);
      } finally { setChecking(false); }
    })();
  }, [pid, address, getReadContracts]);

  const certifiedCount = stages.filter((s) => s.status === "CERTIFIED").length;
  const myStage = actorStages[0];
  const list = Object.values(pipelines).sort((a, b) => a.id - b.id);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-medium text-gray-900">Pipeline #{pid}</h1>
          <p className="text-sm text-gray-500">
            {checking ? "checking your role…" : role
              ? <>You are <span className="text-green-600">{role}</span></>
              : <span className="text-amber-600">You have no role in this pipeline</span>}
          </p>
        </div>
        <select value={pid} onChange={(e) => setPid(Number(e.target.value))}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white">
          {list.length ? list.map((p) => (
            <option key={p.id} value={p.id}>#{p.id} — {p.name}</option>
          )) : <option value={pid}>#{pid}</option>}
        </select>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-6">
        <Stat label="Progress" value={`${certifiedCount} / ${stages.length}`} />
        <Stat label="Your role" value={role || "—"} />
        <Stat label="Your stage" value={myStage || "—"} />
      </div>

      <div className="text-sm text-gray-500 mb-3">Certification chain</div>
      <div className="space-y-2.5">
        {stages.map((s) => {
          const mine = actorStages.includes(s.name);
          const isCert = s.status === "CERTIFIED";
          const isReady = s.status === "READY";
          const highlight = mine && !isCert;
          const stageMap = Object.fromEntries(stages.map((x) => [x.name, x]));
          return (
            <div key={s.name}
              className={`rounded-xl px-4 py-3 border ${highlight ? "border-blue-500 border-2 bg-blue-50/40" : "border-gray-200"} ${!mine && !isCert ? "opacity-60" : ""}`}>
              <div className="flex items-center justify-between">
                <div className="text-sm">
                  <span className="font-medium">{s.label}</span>
                  {mine && <span className="text-blue-600"> · your task</span>}
                  {!mine && s.requiredRole && <span className="text-gray-400"> · {s.requiredRole}</span>}
                  {!s.requiredRole && <span className="text-gray-400"> · root</span>}
                </div>
                <span className={`text-xs ${statusStyle[s.status]}`}>{isCert ? "✓ certified" : s.status.toLowerCase()}</span>
              </div>

              {/* certified: show hash + submitter + timestamp */}
              {isCert && (
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-gray-400 font-mono">
                  <span className="truncate" title={s.hash}>hash: {s.hash ? s.hash.slice(0, 18) + "…" : "—"}</span>
                  <span>by: {s.submitter ? short(s.submitter) : "—"}</span>
                  <span className="col-span-2">{s.ts ? new Date(s.ts * 1000).toLocaleString() : ""}</span>
                </div>
              )}

              {/* actor's own stage when ready: show upstream inputs panel */}
              {highlight && isReady && s.parents.length > 0 && (
                <div className="mt-3 rounded-lg bg-white border border-blue-200 px-3 py-2">
                  <div className="text-xs font-medium text-blue-700 mb-1.5">Your upstream inputs</div>
                  <div className="space-y-1.5">
                    {s.parents.map((p) => {
                      const ps = stageMap[p];
                      return (
                        <div key={p} className="text-xs">
                          <div className="flex items-center gap-2">
                            <span className="text-green-600 font-medium">✓ {ps?.label || p}</span>
                            <span className="text-gray-400">certified by {ps?.submitter ? short(ps.submitter) : "—"}</span>
                            <span className="text-gray-400">{ps?.ts ? new Date(ps.ts * 1000).toLocaleDateString() : ""}</span>
                          </div>
                          <div className="font-mono text-gray-400 truncate mt-0.5" title={ps?.hash}>
                            {ps?.hash ? ps.hash.slice(0, 30) + "…" : "—"}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <p className="mt-2 text-xs text-gray-400">These hashes will be embedded in your certificate as parent links.</p>
                </div>
              )}

              {highlight && isReady && (
                <UploadCertify pid={pid} stage={s} address={address} getWriteContracts={getWriteContracts} onDone={refresh} />
              )}
              {highlight && !isReady && (
                <p className="mt-2 text-xs text-gray-400">Waiting for previous stage(s) to be certified.</p>
              )}
            </div>
          );
        })}
        {loading && <p className="text-gray-400 text-sm text-center py-2">loading…</p>}
      </div>

      <a href={AMOY.explorer} target="_blank" rel="noreferrer"
        className="mt-5 inline-block text-sm text-blue-600 hover:underline">View contract on PolygonScan ↗</a>
    </div>
  );
}

function UploadCertify({ pid, stage, address, getWriteContracts, onDone }) {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function uploadAndCertify() {
    setMsg(null);
    if (!files.length) { setMsg({ type: "err", text: "Choose at least one output file." }); return; }
    try {
      setBusy(true);
      setMsg({ type: "info", text: "Uploading output…" });
      const up = await api.uploadOutput(pid, stage.name, files);

      setMsg({ type: "info", text: "Building manifest…" });
      const built = await api.buildStageManifest({
        pipeline_id: pid, stage: stage.name, files: up.saved, actor: address,
      });
      const h = built.manifest_sha256;
      const parents = built.parents || [];

      setMsg({ type: "info", text: "Confirm in MetaMask…" });
      const { registry } = await getWriteContracts();
      const opts = await amoyTxOpts(registry.storeCertificate, pid, h, stage.name, parents);
      const tx = await registry.storeCertificate(pid, h, stage.name, parents, opts);
      const rcpt = await tx.wait();

      await api.saveStageHash({
        pipeline_id: pid, stage: stage.name, manifest_sha256: h,
        tx_id: tx.hash, block_id: String(rcpt.blockNumber),
      }).catch(() => {});
      setMsg({ type: "ok", text: `${stage.label} certified on-chain.` });
      onDone && onDone();
    } catch (e) {
      setMsg({ type: "err", text: e.shortMessage || e.message || "Failed." });
    } finally { setBusy(false); }
  }

  return (
    <div className="mt-3">
      <div className="flex gap-2 text-xs text-green-600 mb-2">
        <span>✓ role ok</span><span>✓ parents ready</span>
      </div>
      <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files))}
        className="block w-full text-sm text-gray-600 mb-2
                   file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0
                   file:text-sm file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200" />
      {files.length > 0 && (
        <div className="text-xs text-gray-500 mb-2">{files.length} file(s): {files.map((f) => f.name).join(", ")}</div>
      )}
      <button onClick={uploadAndCertify} disabled={busy}
        className="w-full rounded-lg bg-blue-600 text-white py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition">
        {busy ? "Working…" : "Upload & certify with my wallet"}
      </button>
      {msg && <p className={`mt-2 text-sm ${msg.type === "err" ? "text-red-600" : msg.type === "ok" ? "text-green-600" : "text-gray-500"}`}>{msg.text}</p>}
    </div>
  );
}

function Stat({ label, value, valueClass = "" }) {
  return (
    <div className="rounded-lg bg-gray-50 px-4 py-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-2xl font-medium ${valueClass}`}>{value}</div>
    </div>
  );
}