import { useState, useEffect } from "react";
import { api } from "../api";
import { amoyTxOpts } from "../txopts";
import PipelinePicker from "./PipelinePicker";

// Admin certifies the two ROOT stages (dataset, environment). No role needed.
// Backend builds the manifest + hash; admin signs storeCertificate in MetaMask.
export default function CertifyRoots({ ctx }) {
  const pid = ctx.selectedPipeline;

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium text-gray-900 mb-1">Certify Dataset &amp; Environment</h1>
          <p className="text-sm text-gray-500">Pipeline #{pid} · root stages (no role required)</p>
        </div>
        <PipelinePicker ctx={ctx} />
      </div>

      <div className="space-y-4">
        <RootCard ctx={ctx} pid={pid} stage="dataset"
          title="Dataset" desc="Upload your dataset file. The backend hashes it into a manifest; you sign the on-chain certificate." />
        <RootCard ctx={ctx} pid={pid} stage="environment"
          title="Environment" desc="Upload your dependency lock file (e.g. requirements.txt). The backend auto-snapshots the Python environment and builds the manifest; you sign on-chain." />
      </div>

      <p className="mt-6 text-xs text-gray-400">
        Only the manifest hash goes on-chain — never the files themselves.
      </p>
    </div>
  );
}

function RootCard({ ctx, pid, stage, title, desc }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [hash, setHash] = useState(null);
  const [alreadyCertified, setAlreadyCertified] = useState(false);
  const [checking, setChecking] = useState(true);
  const [datasetFiles, setDatasetFiles] = useState([]);
  const [uploadedPath, setUploadedPath] = useState(null);

  // On load, check if this stage is already certified on-chain.
  useEffect(() => {
    (async () => {
      setChecking(true);
      try {
        const contracts = await ctx.getReadContracts();
        const res = await api.stageHashes(pid).catch(() => ({ stage_hashes: {} }));
        const h = res.stage_hashes?.[stage];
        if (h && contracts) {
          const ok = await contracts.registry.isCertified(pid, h);
          setAlreadyCertified(ok);
          if (ok) setHash(h);
        } else {
          setAlreadyCertified(false);
        }
      } catch {
        setAlreadyCertified(false);
      } finally {
        setChecking(false);
      }
    })();
  }, [ctx, pid, stage]);

  async function certify() {
    setMsg(null);
    try {
      setBusy(true);
      let savedPath = uploadedPath;
      if (!savedPath) {
        if (!datasetFiles.length) {
          setMsg({ type: "err", text: `Choose a ${stage === "dataset" ? "dataset" : "dependency lock"} file first.` });
          setBusy(false);
          return;
        }
        setMsg({ type: "info", text: "Uploading file…" });
        const up = await api.uploadAdminDataset(pid, datasetFiles);
        savedPath = up.saved[0];
        setUploadedPath(savedPath);
      }
      setMsg({ type: "info", text: "Building manifest…" });
      const build = stage === "dataset"
        ? await api.buildDatasetManifest(pid, savedPath)
        : await api.buildEnvManifest(pid, savedPath);
      const manifestHash = build.manifest_sha256;
      setHash(manifestHash);

      setMsg({ type: "info", text: "Confirm in MetaMask…" });
      const { registry } = await ctx.getWriteContracts();
      const h = manifestHash.startsWith("0x") ? manifestHash : "0x" + manifestHash;
      if (h.length !== 66) throw new Error(`Bad manifest hash length ${h.length} (need 66).`);

      // guard: if this exact hash is already on-chain, stop before sending
      const exists = await registry.isCertified(pid, h);
      if (exists) {
        setAlreadyCertified(true);
        setMsg({ type: "ok", text: `${title} is already certified.` });
        return;
      }

      const opts = await amoyTxOpts(registry.storeCertificate, pid, h, stage, []);
      const tx = await registry.storeCertificate(pid, h, stage, [], opts);
      const rcpt = await tx.wait();

      await api.saveStageHash({
        pipeline_id: pid, stage, manifest_sha256: h,
        tx_id: tx.hash, block_id: String(rcpt.blockNumber),
      }).catch(() => {});
      setAlreadyCertified(true);
      setMsg({ type: "ok", text: `${title} certified on-chain.` });
    } catch (e) {
      setMsg({ type: "err", text: e.shortMessage || e.message || "Failed." });
    } finally { setBusy(false); }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-start justify-between">
        <div className="pr-4 flex-1">
          <div className="text-sm font-medium text-gray-900">{title}</div>
          <div className="text-sm text-gray-500 mt-1">{desc}</div>
          {!alreadyCertified && (
            <div className="mt-3">
              <input
                type="file"
                onChange={(e) => { setDatasetFiles(Array.from(e.target.files)); setUploadedPath(null); }}
                className="block text-sm text-gray-500
                  file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0
                  file:text-sm file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200"
              />
              {datasetFiles.length > 0 && (
                <p className="text-xs text-gray-400 mt-1">{datasetFiles[0].name}</p>
              )}
            </div>
          )}
          {hash && <div className="text-xs text-gray-400 mt-2 break-all">hash: {hash}</div>}
        </div>
        {checking ? (
          <span className="shrink-0 text-sm text-gray-400">checking…</span>
        ) : alreadyCertified ? (
          <span className="shrink-0 inline-flex items-center gap-1 rounded-lg bg-green-50 text-green-700 px-4 py-2 text-sm font-medium">
            ✓ Certified
          </span>
        ) : (
          <button onClick={certify} disabled={busy}
            className="shrink-0 rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition">
            {busy ? "…" : "Certify"}
          </button>
        )}
      </div>
      {msg && <p className={`mt-3 text-sm ${msg.type === "err" ? "text-red-600" : msg.type === "ok" ? "text-green-600" : "text-gray-500"}`}>{msg.text}</p>}
    </div>
  );
}