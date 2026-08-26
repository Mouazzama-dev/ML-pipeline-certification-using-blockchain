import { useState, useEffect } from "react";
import { api } from "../api";

// A small dropdown to choose which pipeline the screen operates on.
// Reads pipeline names from the backend and sets ctx.selectedPipeline.
export default function PipelinePicker({ ctx }) {
  const [pipelines, setPipelines] = useState({});

  useEffect(() => {
    api.listPipelines().then((r) => setPipelines(r.pipelines || {})).catch(() => {});
  }, []);

  const list = Object.values(pipelines).sort((a, b) => a.id - b.id);

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-500">Pipeline</span>
      <select
        value={ctx.selectedPipeline}
        onChange={(e) => ctx.setSelectedPipeline(Number(e.target.value))}
        className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white">
        {list.length ? list.map((p) => (
          <option key={p.id} value={p.id}>#{p.id} — {p.name}</option>
        )) : <option value={ctx.selectedPipeline}>#{ctx.selectedPipeline}</option>}
      </select>
    </div>
  );
}
