import { useState, useEffect } from "react";
import { id as keccakId } from "ethers";
import { STAGES } from "../config";
import { api } from "../api";
import { short } from "../ui";
import { amoyTxOpts } from "../txopts";
import PipelinePicker from "./PipelinePicker";

export default function RoleManagement({ ctx }) {
  const pid = ctx.selectedPipeline;
  const [actors, setActors] = useState([]);
  const [stage, setStage] = useState("cleaning");
  const [roleName, setRoleName] = useState("DATA_CLEANER");
  const [actorName, setActorName] = useState("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function loadActors() {
    const { actors } = await api.listActors(pid).catch(() => ({ actors: [] }));
    setActors(actors || []);
  }
  useEffect(() => { loadActors(); }, [pid]);

  async function grant() {
    setMsg(null);
    if (!/^0x[a-fA-F0-9]{40}$/.test(address.trim())) { setMsg({ type: "err", text: "Enter a valid 0x address." }); return; }
    try {
      setBusy(true);
      const { roleManager } = await ctx.getWriteContracts();
      const role = keccakId(roleName);
      const acct = address.trim();

      // helper: explicit Amoy gas fees so reverts show a real reason and
      // transactions clear Amoy's minimum gas tip.
      const withGas = async (fn, ...args) => {
        const opts = await amoyTxOpts(fn, ...args);
        const tx = await fn(...args, opts);
        return tx.wait();
      };

      // ensure the stage is mapped to this role, then grant to the actor
      setMsg({ type: "info", text: "Confirm in MetaMask (set stage role)…" });
      await withGas(roleManager.setStageRole, pid, stage, role);
      setMsg({ type: "info", text: "Confirm in MetaMask (grant role)…" });
      await withGas(roleManager.grantRole, pid, role, acct);
      // save display name off-chain
      await api.saveActor(pid, { address: acct, name: actorName.trim() || "Actor", role: roleName });
      setMsg({ type: "ok", text: `Granted ${roleName} to ${short(acct)} for ${stage}.` });
      setAddress(""); setActorName("");
      loadActors();
    } catch (e) { setMsg({ type: "err", text: e.shortMessage || e.message || "Failed." }); }
    finally { setBusy(false); }
  }

  async function revoke(a) {
    try {
      setBusy(true);
      const { roleManager } = await ctx.getWriteContracts();
      const role = keccakId(a.role);
      const opts = await amoyTxOpts(roleManager.revokeRole, pid, role, a.address);
      const tx = await roleManager.revokeRole(pid, role, a.address, opts);
      await tx.wait();
      setMsg({ type: "ok", text: `Revoked ${a.role} from ${short(a.address)}.` });
    } catch (e) { setMsg({ type: "err", text: e.shortMessage || e.message || "Failed." }); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium text-gray-900 mb-1">Role Management</h1>
          <p className="text-sm text-gray-500">Pipeline #{pid} · assign and revoke actor roles</p>
        </div>
        <PipelinePicker ctx={ctx} />
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">
        <div className="px-5 py-3 border-b border-gray-100 text-sm font-medium">Actors</div>
        <table className="w-full text-sm">
          <thead><tr className="text-gray-500 text-left">
            <th className="font-normal px-5 py-2">Address</th><th className="font-normal px-5 py-2">Name</th>
            <th className="font-normal px-5 py-2">Role</th><th className="font-normal px-5 py-2"></th>
          </tr></thead>
          <tbody>
            {actors.map((a, i) => (
              <tr key={i} className="border-t border-gray-100">
                <td className="px-5 py-3 font-mono text-xs">{short(a.address)}</td>
                <td className="px-5 py-3">{a.name}</td>
                <td className="px-5 py-3"><span className="text-xs bg-blue-50 text-blue-700 px-2 py-1 rounded">{a.role}</span></td>
                <td className="px-5 py-3 text-right"><button onClick={() => revoke(a)} disabled={busy} className="text-red-600 hover:underline text-xs">Revoke</button></td>
              </tr>
            ))}
            {!actors.length && <tr><td colSpan="4" className="px-5 py-6 text-center text-gray-400">No actors assigned yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="text-sm font-medium mb-3">Assign role</div>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <select value={stage} onChange={(e) => setStage(e.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
            {STAGES.filter((s) => s.requiredRole).map((s) => <option key={s.name}>{s.name}</option>)}
          </select>
          <select value={roleName} onChange={(e) => setRoleName(e.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
            <option>DATA_CLEANER</option><option>MODEL_TRAINER</option><option>REVIEWER</option>
          </select>
          <input value={actorName} onChange={(e) => setActorName(e.target.value)} placeholder="Actor name (e.g. Data Cleaner)" className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          <input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="0x actor address" className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </div>
        <button onClick={grant} disabled={busy} className="rounded-lg bg-blue-600 text-white px-5 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition">
          {busy ? "…" : "Grant role"}
        </button>
        {msg && <p className={`mt-3 text-sm ${msg.type === "err" ? "text-red-600" : msg.type === "ok" ? "text-green-600" : "text-gray-500"}`}>{msg.text}</p>}
        <p className="text-xs text-gray-400 mt-2">Maps the stage to the role and grants it — two MetaMask signatures.</p>
      </div>
    </div>
  );
}