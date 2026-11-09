// 백엔드 API 호출을 한곳에 모은 파일. 다른 파일은 API.xxx()만 부른다.
const API = (() => {
  const BASE = ((window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "").replace(/\/+$/, "");

  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  const FIELD_NAMES = { date: "날짜", value: "환율", memo: "메모", message: "질문", title: "제목", messages: "메시지" };

  // FastAPI 422 응답의 detail 배열을 한국어 한 줄로 바꾼다
  function validationMessage(item) {
    const field = FIELD_NAMES[item.loc && item.loc[item.loc.length - 1]] || "";
    const ctx = item.ctx || {};
    const byType = {
      less_than: `${ctx.lt} 미만이어야 해요`,
      greater_than: `${ctx.gt}보다 커야 해요`,
      string_too_long: `${ctx.max_length}자 이하로 입력하세요`,
      string_too_short: "내용을 입력하세요",
      missing: "값을 입력하세요",
      json_invalid: "보낸 내용의 형식이 올바르지 않아요",
    };
    let text = byType[item.type];
    if (!text && item.type && item.type.startsWith("date")) text = "날짜 형식이 올바르지 않아요";
    if (!text) text = String(item.msg || "").replace(/^Value error,\s*/, "");
    return field ? `${field}: ${text}` : text;
  }

  function messageFrom(data, status) {
    if (data && typeof data.detail === "string") return data.detail;
    if (data && Array.isArray(data.detail)) return data.detail.map(validationMessage).join(" / ");
    return `요청을 처리하지 못했어요 (오류 ${status}).`;
  }

  // 응답을 받아 오류를 검사한 뒤 Response를 그대로 돌려준다
  async function send(path, { method = "GET", body, timeout = 60000 } = {}) {
    if (!BASE) throw new ApiError(0, "API 주소가 설정되지 않았어요. config.js를 확인하세요.");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const res = await fetch(BASE + path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new ApiError(res.status, messageFrom(data, res.status));
      }
      return res;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (err.name === "AbortError") throw new ApiError(0, "서버 응답이 너무 늦어요. 잠시 후 다시 시도하세요.");
      throw new ApiError(0, "서버에 연결할 수 없어요. 서버가 켜져 있는지 확인하세요.");
    } finally {
      clearTimeout(timer);
    }
  }

  async function request(path, options) {
    const res = await send(path, options);
    if (res.status === 204) return null;
    return res.json();
  }

  // 파일 내려받기: 응답을 Blob으로 받아 브라우저 다운로드를 띄운다
  async function download(path, filename) {
    const res = await send(path, { timeout: 60000 });
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const query = (params) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") q.set(k, v); });
    const s = q.toString();
    return s ? `?${s}` : "";
  };

  return {
    ApiError,
    health: () => request("/health", { timeout: 15000 }),
    summary: () => request("/api/data/summary"),
    series: (range) => request(`/api/data/series?range=${range}`),
    statistics: (range) => request(`/api/data/statistics?range=${range}`),
    exportData: (format) => download(`/api/data/export?format=${format}`, `yen_rates.${format}`),
    listData: (params) => request(`/api/data${query(params)}`),
    createData: (body) => request("/api/data", { method: "POST", body }),
    updateData: (id, body) => request(`/api/data/${encodeURIComponent(id)}`, { method: "PUT", body }),
    deleteData: (id) => request(`/api/data/${encodeURIComponent(id)}`, { method: "DELETE" }),
    listConversations: () => request("/api/conversations?limit=50"),
    getConversation: (id) => request(`/api/conversations/${encodeURIComponent(id)}`),
    deleteConversation: (id) => request(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }),
    chat: (body) => request("/api/chat", { method: "POST", body, timeout: 90000 }),
  };
})();
