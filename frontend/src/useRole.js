import { useState, useEffect, useCallback } from "react";
import { STAGES } from "./config";
import { api } from "./api";

// Detects whether the wallet is an admin or an actor on ANY pipeline — not just
// the default one. Login should succeed if the wallet has a role anywhere; the
// portal then lets them pick the specific pipeline.
export function useRole(getReadContracts, address) {
  const [loading, setLoading] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [actorStages, setActorStages] = useState([]);
  const [role, setRole] = useState(null);
  const [error, setError] = useState(null);

  const detect = useCallback(async () => {
    if (!address) return;
    setLoading(true);
    setError(null);
    try {
      const contracts = await getReadContracts();
      if (!contracts) return;
      const { roleManager } = contracts;

      // which pipeline ids exist? use backend names, fall back to nextPipelineId
      let ids = [];
      try {
        const r = await api.listPipelines();
        ids = Object.values(r.pipelines || {}).map((p) => p.id);
      } catch { /* ignore */ }
      if (!ids.length) {
        try {
          const next = await roleManager.nextPipelineId();
          for (let i = 1; i < Number(next); i++) ids.push(i);
        } catch { /* ignore */ }
      }
      // de-dup + sort
      ids = [...new Set(ids)].sort((a, b) => a - b);

      const ZERO = "0x" + "0".repeat(64);
      const gated = STAGES.filter((s) => s.requiredRole);
      let admin = false;
      const stagesFound = new Set();
      let firstRole = null;

      for (const pid of ids) {
        // admin on any pipeline?
        try {
          const a = await roleManager.pipelineAdmin(pid);
          if (a.toLowerCase() === address.toLowerCase()) admin = true;
        } catch { /* ignore */ }

        // actor role on any pipeline? (role set AND wallet holds it — no fail-open)
        for (const s of gated) {
          try {
            const sr = await roleManager.getStageRole(pid, s.name);
            if (!sr || sr === ZERO) continue;
            const has = await roleManager.hasRole(pid, sr, address);
            if (has) {
              stagesFound.add(s.name);
              if (!firstRole) firstRole = s.requiredRole;
            }
          } catch { /* ignore */ }
        }
      }

      setIsAdmin(admin);
      setActorStages([...stagesFound]);
      setRole(firstRole);
    } catch (e) {
      setError(e.message || "Failed to detect role.");
    } finally {
      setLoading(false);
    }
  }, [getReadContracts, address]);

  useEffect(() => { detect(); }, [detect]);

  return { loading, isAdmin, actorStages, role, error, refresh: detect };
}