export function short(addr) {
  return addr ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : "";
}

export const statusStyle = {
  CERTIFIED: "text-green-600",
  READY: "text-blue-600",
  LOCKED: "text-gray-400",
};
