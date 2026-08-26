// Calls to the off-chain admin support API (admin_api.py).
const BASE = import.meta.env.VITE_ADMIN_API || "http://localhost:8080";

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export const api = {
  listPipelines: () => req("/pipelines"),
  getPipeline: (id) => req(`/pipelines/${id}`),
  savePipeline: (p) => req("/pipelines", { method: "POST", body: JSON.stringify(p) }),
  listActors: (id) => req(`/actors/${id}`),
  saveActor: (id, a) => req(`/actors/${id}`, { method: "POST", body: JSON.stringify(a) }),
  uploadAdminDataset: async (pipeline_id, fileList) => {
    const fd = new FormData();
    for (const f of fileList) fd.append("files", f);
    const res = await fetch(`${BASE}/upload/admin/${pipeline_id}`, { method: "POST", body: fd });
    if (!res.ok) {
      let d; try { d = (await res.json()).detail; } catch { d = res.statusText; }
      throw new Error(typeof d === "string" ? d : JSON.stringify(d));
    }
    return res.json();
  },
  buildDatasetManifest: (pipeline_id, dataset_path) =>
    req("/manifest/dataset", { method: "POST", body: JSON.stringify({ pipeline_id, dataset_path }) }),
  buildEnvManifest: (pipeline_id, dependency_lock_path) =>
    req("/manifest/environment", { method: "POST", body: JSON.stringify({ pipeline_id, dependency_lock_path }) }),
  stageHashes: (id) => req(`/stage-hashes/${id}`),
  saveStageHash: (payload) => req("/stage-hash", { method: "POST", body: JSON.stringify(payload) }),

  // user portal: upload actor output files (multipart), then build manifest
  uploadOutput: async (pid, stage, fileList) => {
    const fd = new FormData();
    for (const f of fileList) fd.append("files", f);
    const res = await fetch(`${BASE}/upload/${pid}/${stage}`, { method: "POST", body: fd });
    if (!res.ok) {
      let d; try { d = (await res.json()).detail; } catch { d = res.statusText; }
      throw new Error(typeof d === "string" ? d : JSON.stringify(d));
    }
    return res.json();
  },
  buildStageManifest: (payload) => req("/manifest/stage", { method: "POST", body: JSON.stringify(payload) }),
};