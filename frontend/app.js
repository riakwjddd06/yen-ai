// 화면 동작. 프레임워크 없이 DOM을 직접 다룬다.
(() => {
  const $ = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";

  const state = {
    ready: false,            // 서버 연결 여부
    conversationId: null,    // 지금 보고 있는 대화
    conversationTitle: "",
    sending: false,
    cursor: null,            // 데이터 목록 다음 페이지
    filter: { start: "", end: "" },
    range: "1y",             // 그래프 기간
    seriesCache: {},         // 기간별 그래프 데이터
    series: null,
  };

  /* ── 공통 도우미 ───────────────────────── */
  const won = (v) => Number(v).toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function todayLocal() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function shortTime(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  let toastTimer;
  function toast(message, kind = "info") {
    const el = $("toast");
    el.textContent = message;
    el.dataset.kind = kind;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, kind === "error" ? 5000 : 2500);
  }

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    Object.entries(props).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;  // 사용자 입력은 항상 textContent로 넣는다 (XSS 방지)
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    });
    children.forEach((c) => node.append(c));
    return node;
  }

  function svg(tag, attrs = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  }

  /* ── 1. 서버 깨우기 (Render 무료 서버 대응) ───────── */
  async function wakeServer() {
    const status = $("server-status");
    const bannerTimer = setTimeout(() => { $("wake-banner").hidden = false; }, 3000);

    for (let attempt = 1; attempt <= 8; attempt += 1) {
      try {
        await API.health();
        clearTimeout(bannerTimer);
        $("wake-banner").hidden = true;
        status.textContent = "서버 연결됨";
        status.dataset.state = "ok";
        state.ready = true;
        setChatEnabled(true);
        return true;
      } catch (err) {
        status.textContent = `서버 연결 중 (${attempt}/8)`;
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
    clearTimeout(bannerTimer);
    $("wake-banner").hidden = true;
    status.textContent = "서버에 연결하지 못했어요. 새로고침해 보세요.";
    status.dataset.state = "error";
    return false;
  }

  /* ── 2. 환율 요약 ───────────────────────── */
  async function loadSummary() {
    try {
      renderSummary(await API.summary());
    } catch (err) {
      $("rate-date").textContent = `요약을 불러오지 못했어요. ${err.message}`;
    }
  }

  function renderSummary(s) {
    const m = s.metrics;
    $("rate-value").textContent = won(m.latest.value);
    $("rate-date").textContent = `100엔, ${m.latest.date} 한국은행 매매기준율`;

    const change = m.change_1y_pct;
    const delta = $("rate-delta");
    delta.textContent = change < 0 ? `1년 전보다 ${Math.abs(change).toFixed(1)}% 싸요` : `1년 전보다 ${change.toFixed(1)}% 비싸요`;
    delta.dataset.dir = change < 0 ? "down" : "up";

    const p = s.position.percentile_1y;
    const zone = p <= 20 ? "cheap" : p >= 80 ? "dear" : "mid";
    const marker = $("gauge-marker");
    marker.hidden = false;
    marker.dataset.zone = zone;
    marker.style.left = `${Math.min(Math.max(p, 2), 98)}%`;
    const verdict = { cheap: "엔화가 싼 편이에요", mid: "중간 수준이에요", dear: "엔화가 비싼 편이에요" }[zone];
    $("gauge-caption").textContent = `최근 1년 중 하위 ${Math.round(p)}%, ${verdict}`;
    $("gauge").setAttribute("aria-label", `최근 1년 범위에서 하위 ${Math.round(p)}% 위치`);

    $("fact-score").textContent = `${s.travel.rate_score}점`;
    $("fact-score-sub").textContent = s.travel.rate_label;
    const [trendWord, trendChange] = s.trend.split(",").map((t) => t.trim());
    $("fact-trend").textContent = trendWord;
    $("fact-trend-sub").textContent = trendChange || "";
    const [from, to] = s.period.split(" ~ ");
    $("fact-period").textContent = `${s.count.toLocaleString("ko-KR")}개 영업일`;
    $("fact-period-sub").textContent = `${from} – ${to}`;
  }

  /* ── 3. 그래프 ───────────────────────── */
  async function loadSeries(range, { force = false } = {}) {
    state.range = range;
    document.querySelectorAll(".period-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.range === range)));
    try {
      if (force || !state.seriesCache[range]) state.seriesCache[range] = await API.series(range);
      drawChart(state.seriesCache[range]);
    } catch (err) {
      $("chart").setAttribute("aria-label", "그래프를 불러오지 못했어요");
      toast(`그래프를 불러오지 못했어요. ${err.message}`, "error");
    }
  }

  function drawChart(series) {
    state.series = series;
    const { dates, values } = series;
    const W = 1000, H = 200, PAD = 10;
    const hi = Math.max(...values), lo = Math.min(...values);
    const span = hi - lo || 1;
    const x = (i) => (values.length === 1 ? W : (i / (values.length - 1)) * W);
    const y = (v) => PAD + ((hi - v) / span) * (H - PAD * 2);

    // 날짜 → 가장 가까운 점의 x 좌표 (이벤트 구간 표시용)
    const xOfDate = (d) => {
      let idx = dates.findIndex((day) => day >= d);
      if (idx === -1) idx = dates.length - 1;
      return x(idx);
    };

    const root = $("chart-svg");
    root.replaceChildren();
    series.events.forEach((e) => {
      const x1 = xOfDate(e.start_date), x2 = xOfDate(e.end_date);
      const rect = svg("rect", { class: "chart-band", x: x1, y: 0, width: Math.max(x2 - x1, 4), height: H });
      root.append(rect);
    });
    root.append(svg("line", { class: "chart-avg", x1: 0, x2: W, y1: y(series.average), y2: y(series.average) }));
    const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    root.append(svg("path", { class: "chart-line", d }));

    // 마지막 점과 값 (HTML로 그려서 찌그러지지 않게)
    const chartH = $("chart").clientHeight;
    const lastTop = (y(values[values.length - 1]) / H) * chartH;
    const dot = $("chart-dot");
    dot.hidden = false;
    dot.style.left = "100%";
    dot.style.top = `${lastTop}px`;
    const last = $("chart-last");
    last.textContent = won(values[values.length - 1]);
    last.style.top = lastTop < 34 ? `${lastTop + 10}px` : `${lastTop - 30}px`;  // 점 위쪽에, 너무 위면 아래쪽에

    // 범례와 x축
    $("legend-avg").textContent = `평균 ${won(series.average)}`;
    $("legend-range").textContent = `최고 ${won(series.max.value)} (${series.max.date}), 최저 ${won(series.min.value)} (${series.min.date})`;
    const axis = $("chart-axis");
    axis.replaceChildren();
    [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
      const i = Math.round(t * (dates.length - 1));
      const [yy, mm, dd] = dates[i].split("-");
      const label = series.range === "3m" ? `${Number(mm)}월 ${Number(dd)}일` : `${yy}.${mm}`;  // 3개월은 날짜까지
      axis.append(el("span", { text: label, style: `left: ${t * 100}%` }));
    });

    $("chart").setAttribute(
      "aria-label",
      `${series.start}부터 ${series.end}까지 원/엔 환율 그래프. 최고 ${won(series.max.value)}원, 최저 ${won(series.min.value)}원, 마지막 ${won(values[values.length - 1])}원`,
    );
  }

  // 마우스를 올리면 그 날짜의 환율과 기록된 이유를 보여준다
  function bindChartHover() {
    const chart = $("chart");
    const tip = $("chart-tip");
    const guide = $("chart-guide");

    chart.addEventListener("pointermove", (e) => {
      const s = state.series;
      if (!s) return;
      const rect = chart.getBoundingClientRect();
      const ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
      const i = Math.round(ratio * (s.dates.length - 1));
      const day = s.dates[i];
      const event = s.events.find((ev) => ev.start_date <= day && ev.end_date >= day);

      guide.hidden = false;
      guide.style.left = `${ratio * 100}%`;
      tip.replaceChildren(
        el("span", { text: day }),
        el("strong", { text: `${won(s.values[i])}원` }),
        ...(event ? [el("em", { text: event.title })] : []),
      );
      tip.hidden = false;
      tip.style.left = `${ratio * 100}%`;
      tip.dataset.flip = String(ratio > 0.7);
    });
    chart.addEventListener("pointerleave", () => { tip.hidden = true; guide.hidden = true; });
  }

  /* ── 4. 대화 기록 ───────────────────────── */
  async function loadConversations() {
    try {
      renderConversations(await API.listConversations());
    } catch (err) {
      toast(`대화 기록을 불러오지 못했어요. ${err.message}`, "error");
    }
  }

  function renderConversations(items) {
    const list = $("conv-list");
    list.replaceChildren();
    $("conv-empty").hidden = items.length > 0;

    items.forEach((c) => {
      const li = el("li", { class: "conv-item" });
      if (c.id === state.conversationId) li.setAttribute("aria-current", "true");
      li.append(
        el("button", { class: "conv-open", type: "button", onclick: () => openConversation(c.id) }, [
          el("span", { class: "conv-title", text: c.title }),
          el("span", { class: "conv-meta", text: `${shortTime(c.updated_at)}, 메시지 ${c.message_count}개` }),
        ]),
        el("button", {
          class: "conv-delete", type: "button", "aria-label": `"${c.title}" 대화 삭제`,
          onclick: () => removeConversation(c.id, c.title), text: "×",
        }),
      );
      list.append(li);
    });
  }

  function setCurrent(id, title) {
    state.conversationId = id;
    state.conversationTitle = title || "";
    $("chat-current").textContent = id ? `지금 보는 대화: ${title}` : "새 대화";
  }

  async function openConversation(id) {
    try {
      const conv = await API.getConversation(id);
      setCurrent(conv.id, conv.title);
      clearMessages();
      conv.messages.forEach((m) => addMessage(m.role, m.content));
      loadConversations();
      if (window.matchMedia("(max-width: 1100px)").matches) $("messages").scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      toast(`대화를 불러오지 못했어요. ${err.message}`, "error");
    }
  }

  async function removeConversation(id, title) {
    if (!confirm(`"${title}" 대화를 삭제할까요? 되돌릴 수 없어요.`)) return;
    try {
      await API.deleteConversation(id);
      if (state.conversationId === id) newChat();
      toast("대화를 삭제했어요.");
      loadConversations();
    } catch (err) {
      toast(`삭제하지 못했어요. ${err.message}`, "error");
    }
  }

  function newChat() {
    setCurrent(null, "");
    clearMessages();
    $("chat-intro").hidden = false;
    loadConversations();
    $("chat-input").focus();
  }

  /* ── 5. 채팅 ───────────────────────── */
  function setChatEnabled(on) {
    $("chat-input").disabled = !on;
    $("send-btn").disabled = !on;
    document.querySelectorAll(".chip").forEach((b) => { b.disabled = !on; });
  }

  function clearMessages() {
    $("messages").querySelectorAll(".msg").forEach((n) => n.remove());
    $("chat-intro").hidden = true;
  }

  function addMessage(role, text) {
    const node = el("div", { class: `msg msg--${role}`, text });
    $("messages").append(node);
    $("messages").scrollTop = $("messages").scrollHeight;
    return node;
  }

  async function sendMessage(text) {
    const message = text.trim();
    if (!message || state.sending || !state.ready) return;

    state.sending = true;
    setChatEnabled(false);
    $("chat-intro").hidden = true;
    addMessage("user", message);
    $("chat-input").value = "";

    const loading = el("div", { class: "msg msg--loading", "aria-label": "답변을 만드는 중" }, [
      "데이터를 보고 답을 만드는 중", el("span", { class: "dots", "aria-hidden": "true" }, [el("span"), el("span"), el("span")]),
    ]);
    $("messages").append(loading);
    $("messages").scrollTop = $("messages").scrollHeight;

    try {
      const res = await API.chat({ message, ...(state.conversationId ? { conversation_id: state.conversationId } : {}) });
      loading.remove();
      addMessage("assistant", res.reply);
      setCurrent(res.conversation_id, res.title);
      loadConversations();
    } catch (err) {
      loading.remove();
      addMessage("error", `${err.message} 질문은 입력창에 다시 넣어 두었어요.`);
      $("chat-input").value = message;
    } finally {
      state.sending = false;
      setChatEnabled(true);
      $("chat-input").focus();
    }
  }

  /* ── 6. 데이터 관리 ───────────────────────── */
  async function loadData({ reset = false } = {}) {
    if (reset) {
      state.cursor = null;
      $("data-rows").replaceChildren();
    }
    try {
      const res = await API.listData({ limit: 20, order: "desc", start: state.filter.start, end: state.filter.end, cursor: state.cursor });
      res.items.forEach((item) => $("data-rows").append(dataRow(item)));
      state.cursor = res.next_cursor;
      $("more-btn").hidden = !res.next_cursor;
      const shown = $("data-rows").children.length;
      $("data-count").textContent = res.total
        ? `${res.total.toLocaleString("ko-KR")}건 중 ${shown.toLocaleString("ko-KR")}건 표시 (최신순)`
        : "조건에 맞는 데이터가 없어요. 기간을 바꾸거나 위에서 새로 추가해 보세요.";
    } catch (err) {
      $("data-count").textContent = `데이터를 불러오지 못했어요. ${err.message}`;
    }
  }

  function dataRow(item) {
    const tr = el("tr", { "data-id": item.id });
    tr.append(
      el("td", { text: item.date }),
      el("td", { class: "num", text: won(item.value) }),
      el("td", { class: "memo", text: item.memo || "" }),
      el("td", { class: "actions" }, [
        el("button", { class: "btn btn--text btn--small", type: "button", text: "수정", onclick: () => startEdit(tr, item) }),
        el("button", { class: "btn btn--text btn--small btn--danger", type: "button", text: "삭제", onclick: () => removeRow(tr, item) }),
      ]),
    );
    return tr;
  }

  function startEdit(tr, item) {
    const value = el("input", { type: "number", step: "0.01", min: "300.01", max: "2999.99", "aria-label": `${item.date} 환율` });
    value.value = item.value;
    const memo = el("input", { type: "text", maxlength: "200", "aria-label": `${item.date} 메모` });
    memo.value = item.memo || "";

    const save = async () => {
      try {
        const updated = await API.updateData(item.id, { value: Number(value.value), memo: memo.value });
        tr.replaceWith(dataRow(updated));
        toast(`${item.date} 데이터를 수정했어요.`);
        refreshAfterChange();
      } catch (err) {
        toast(`수정하지 못했어요. ${err.message}`, "error");
      }
    };

    tr.replaceChildren(
      el("td", { text: item.date }),
      el("td", { class: "num" }, [value]),
      el("td", {}, [memo]),
      el("td", { class: "actions" }, [
        el("button", { class: "btn btn--primary btn--small", type: "button", text: "저장", onclick: save }),
        el("button", { class: "btn btn--text btn--small", type: "button", text: "취소", onclick: () => tr.replaceWith(dataRow(item)) }),
      ]),
    );
    value.focus();
  }

  async function removeRow(tr, item) {
    if (!confirm(`${item.date} 데이터를 삭제할까요?`)) return;
    try {
      await API.deleteData(item.id);
      tr.remove();
      toast(`${item.date} 데이터를 삭제했어요.`);
      refreshAfterChange();
    } catch (err) {
      toast(`삭제하지 못했어요. ${err.message}`, "error");
    }
  }

  async function addData(event) {
    event.preventDefault();
    const form = event.target;
    const body = { date: form.date.value, value: Number(form.value.value), memo: form.memo.value };
    try {
      const created = await API.createData(body);
      toast(`${created.date} 데이터를 추가했어요.`);
      form.value.value = "";
      form.memo.value = "";
      await loadData({ reset: true });
      const row = $("data-rows").querySelector(`tr[data-id="${created.id}"]`);
      if (row) {
        row.classList.add("is-new");
        row.scrollIntoView({ block: "nearest" });
      }
      refreshAfterChange();
    } catch (err) {
      toast(`추가하지 못했어요. ${err.message}`, "error");
    }
  }

  // 데이터가 바뀌면 요약과 그래프를 다시 받는다
  function refreshAfterChange() {
    state.seriesCache = {};
    loadSummary();
    loadSeries(state.range, { force: true });
  }

  async function exportData(format) {
    try {
      await API.exportData(format);
      toast(`${format.toUpperCase()} 파일을 내려받았어요.`);
    } catch (err) {
      toast(`내보내지 못했어요. ${err.message}`, "error");
    }
  }

  /* ── 이벤트 연결 ───────────────────────── */
  function bindEvents() {
    $("chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendMessage($("chat-input").value); });
    $("chat-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {  // 한글 조합 중 Enter는 무시
        e.preventDefault();
        sendMessage($("chat-input").value);
      }
    });
    document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => sendMessage(chip.textContent)));
    $("new-chat").addEventListener("click", newChat);

    document.querySelectorAll(".period-btn").forEach((b) => b.addEventListener("click", () => loadSeries(b.dataset.range)));
    bindChartHover();
    window.addEventListener("resize", () => { if (state.series) drawChart(state.series); });

    $("add-form").addEventListener("submit", addData);
    $("filter-toggle").addEventListener("click", () => {
      const form = $("filter-form");
      form.hidden = !form.hidden;
      $("filter-toggle").setAttribute("aria-expanded", String(!form.hidden));
      if (!form.hidden) $("filter-start").focus();
    });
    $("filter-form").addEventListener("submit", (e) => {
      e.preventDefault();
      state.filter = { start: $("filter-start").value, end: $("filter-end").value };
      loadData({ reset: true });
    });
    $("filter-reset").addEventListener("click", () => {
      $("filter-start").value = "";
      $("filter-end").value = "";
      state.filter = { start: "", end: "" };
      loadData({ reset: true });
    });
    $("more-btn").addEventListener("click", () => loadData());
    $("export-csv").addEventListener("click", () => exportData("csv"));
    $("export-json").addEventListener("click", () => exportData("json"));
  }

  /* ── 시작 ───────────────────────── */
  async function init() {
    $("add-date").value = todayLocal();
    $("add-date").max = todayLocal();
    bindEvents();
    if (await wakeServer()) {
      loadSummary();
      loadSeries("1y");
      loadConversations();
      loadData({ reset: true });
    }
  }

  init();
})();
