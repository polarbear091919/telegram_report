export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "요청을 완료하지 못했습니다.",
    );
  return body;
}
export const periods = [
  [36500, "전체 기간"],
  [30, "최근 30일"],
  [90, "최근 90일"],
  [180, "최근 180일"],
  [365, "최근 1년"],
];
export const units = [
  ["D", "일별"],
  ["W", "주별"],
  ["M", "월별"],
];
export const fmt = (value) => Number(value || 0).toLocaleString("ko-KR");

export function downloadCSV(rows, name) {
  if (!rows.length) return;
  const keys = Object.keys(rows[0]);
  const cell = (value) => {
    let text = String(value ?? "");
    if (/^[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const csv = [keys, ...rows.map((row) => keys.map((key) => row[key]))]
    .map((row) => row.map(cell).join(","))
    .join("\r\n");
  const url = URL.createObjectURL(
    new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
