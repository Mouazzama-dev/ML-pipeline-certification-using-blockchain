import { useState } from "react";
import { api } from "../api";
import { amoyTxOpts } from "../txopts";

export default function CreatePipeline({ ctx }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function create() {
    setMsg(null);
    if (!name.trim()) { setMsg({ type: "err", text: "Enter a pipeline name." }); return; }
    try {
      setBusy(true);
      // 1. on-chain create (MetaMask)
      const { roleManager } = await ctx.getWriteContracts();
      const opts = await amoyTxOpts(roleManager.createPipeline);
      const tx = await roleManager.createPipeline(opts);
      setMsg({ type: "info", text: "Creating on-chain — confirm in MetaMask…" });
      const receipt = await tx.wait();

      // 2. read new pipeline id from the PipelineCreated event
      let newId = null;
      for (const log of receipt.logs) {
        try {
          const parsed = roleManager.interface.parseLog(log);
          if (parsed && parsed.name === "PipelineCreated") { newId = Number(parsed.args.pipelineId); break; }
        } catch { /* not our event */ }
      }

      // 3. save name/description off-chain
      if (newId != null) {
        await api.savePipeline({ id: newId, name: name.trim(), description: description.trim() });
        setMsg({ type: "ok", text: `Pipeline #${newId} created and named "${name.trim()}".` });
        ctx.setSelectedPipeline(newId);
      } else {
        setMsg({ type: "ok", text: "Pipeline created on-chain (could not read id from event)." });
      }
      setName(""); setDescription("");
    } catch (e) {
      setMsg({ type: "err", text: e.shortMessage || e.message || "Failed." });
    } finally { setBusy(false); }
  }

  return (
    <div>
      <h1 className="text-2xl font-medium text-gray-900 mb-1">Create Pipeline</h1>
      <p className="text-sm text-gray-500 mb-6">Create a new pipeline and become its admin</p>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Pipeline name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Iris ML Pipeline"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows="4" placeholder="Describe this pipeline"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </div>
          <button onClick={create} disabled={busy}
            className="rounded-lg bg-blue-600 text-white px-5 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition">
            {busy ? "Creating…" : "Create Pipeline"}
          </button>
          {msg && <p className={`text-sm ${msg.type === "err" ? "text-red-600" : msg.type === "ok" ? "text-green-600" : "text-gray-500"}`}>{msg.text}</p>}
        </div>

        <div className="bg-gray-50 rounded-xl border border-gray-200 p-5">
          <div className="text-sm font-medium text-gray-700 mb-3">What happens</div>
          <ol className="text-sm text-gray-600 space-y-2 list-decimal list-inside">
            <li>Pipeline is created on-chain</li>
            <li>You become its admin</li>
            <li>You assign roles to actors</li>
            <li>Stages get certified</li>
            <li>Full provenance chain is built</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
