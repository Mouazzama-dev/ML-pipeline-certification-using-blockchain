import { useState, useEffect, useCallback } from "react";
import { STAGES, PIPELINE_ID } from "./config";
import { api } from "./api";

// Reads each stage's certificate status for a given pipeline from the registry,
// using stage hashes from the backend (/stage-hashes), and derives
// CERTIFIED / READY / LOCKED — mirroring the orchestrator's logic.
export function usePipeline(getReadContracts, address, pipelineId = PIPELINE_ID) {
  const [loading, setLoading] = useState(false);
  const [stages, setStages] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!getReadContracts) return;
    setLoading(true);
    setError(null);
    try {
      const contracts = await getReadContracts();
      if (!contracts) return;
      const { registry } = contracts;

      // hashes come from the backend (saved receipts / UI-certified hashes)
      const res = await api.stageHashes(pipelineId).catch(() => ({ stage_hashes: {} }));
      const hashes = res.stage_hashes || {};

      const certified = {};
      const certData  = {};
      for (const s of STAGES) {
        const h = hashes[s.name];
        const ok = h ? await registry.isCertified(pipelineId, h) : false;
        certified[s.name] = ok;
        if (ok) {
          try {
            const c = await registry.getCertificate(pipelineId, h);
            certData[s.name] = { submitter: c.submitter, ts: Number(c.timestamp) };
          } catch { /* ignore */ }
        }
      }

      const out = STAGES.map((s) => {
        let status;
        if (certified[s.name]) status = "CERTIFIED";
        else if (s.parents.every((p) => certified[p])) status = "READY";
        else status = "LOCKED";
        const cd = certData[s.name] || {};
        return { ...s, status, hash: hashes[s.name] || null, submitter: cd.submitter || null, ts: cd.ts || null };
      });
      setStages(out);
    } catch (e) {
      setError(e.message || "Failed to load pipeline.");
    } finally {
      setLoading(false);
    }
  }, [getReadContracts, pipelineId]);

  useEffect(() => { load(); }, [load]);

  return { loading, stages, error, refresh: load };
}