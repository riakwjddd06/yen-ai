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
    statsCache: {},          // 기간별 통계
    series: null,
    showMa: true,            // 20일 이동평균 선 표시
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

  /* ── 날짜 입력: 연, 월, 일 칸 + 목록 ───────────────────────── */
  // 칸을 누르면 아래에 목록이 뜨고, 그대로 숫자를 쳐도 된다.
  // "20150801"을 이어서 치면 연→월→일로 저절로 넘어간다.
  // (브라우저 기본 <select>는 맥에서 누르면 메뉴가 떠서 키보드 입력이 막히므로 직접 만든다)
  const FIRST_YEAR = 2015;
  const daysIn = (y, m) => new Date(y, m, 0).getDate();  // m은 1~12
  const pad2 = (n) => String(n).padStart(2, "0");
  let dateSelectCount = 0;

  function dateSelect(root) {
    const label = root.dataset.label;
    const now = new Date();
    const maxY = now.getFullYear(), maxM = now.getMonth() + 1, maxD = now.getDate();
    const id = `ds${++dateSelectCount}`;
    const list = el("div", { class: "ds-list", role: "listbox", id: `${id}-list`, "aria-label": `${label} 목록` });
    list.hidden = true;

    const makeSeg = (key, part, unit, len, cols) => {
      const input = el("input", {
        type: "text", inputmode: "numeric", autocomplete: "off", maxlength: String(len), placeholder: part,
        role: "combobox", "aria-label": `${label} ${part}`, "aria-expanded": "false",
        "aria-controls": list.id, "aria-autocomplete": "list",
      });
      const box = el("span", { class: `ds-box ds-box--${key}` }, [input, el("span", { class: "ds-unit", "aria-hidden": "true", text: unit })]);
      box.addEventListener("mousedown", (e) => { if (e.target === box || e.target.classList.contains("ds-unit")) { e.preventDefault(); input.focus(); } });
      return { key, input, box, len, cols };
    };
    const Y = makeSeg("y", "연도", "년", 4, 4);
    const M = makeSeg("m", "월", "월", 2, 4);
    const D = makeSeg("d", "일", "일", 2, 7);
    const segs = [Y, M, D];
    root.replaceChildren(...segs.map((s) => s.box), list);

    let active = null;  // 목록이 열린 칸
    let hl = -1;        // 목록에서 강조된 위치
    let opts = [];
    const num = (s) => Number(s.input.value) || 0;

    function choices(s) {
      const y = num(Y), m = num(M);
      if (s === Y) {
        const years = [];
        for (let v = maxY; v >= FIRST_YEAR; v -= 1) years.push({ v, text: String(v), off: false });
        return years;
      }
      if (s === M) return Array.from({ length: 12 }, (_, i) => ({ v: i + 1, text: `${i + 1}월`, off: y === maxY && i + 1 > maxM }));
      const n = daysIn(y || 2024, m >= 1 && m <= 12 ? m : 1);
      return Array.from({ length: n }, (_, i) => ({ v: i + 1, text: String(i + 1), off: y === maxY && m === maxM && i + 1 > maxD }));
    }

    function render() {
      list.dataset.kind = active.key;
      list.style.setProperty("--cols", active.cols);
      list.replaceChildren(...opts.map((o, i) => {
        const opt = el("div", { class: "ds-opt", role: "option", id: `${id}-o${i}`, text: o.text, "aria-selected": String(i === hl) });
        if (o.off) opt.setAttribute("aria-disabled", "true");
        opt.addEventListener("mousedown", (e) => e.preventDefault());  // 입력칸 포커스 유지
        opt.addEventListener("click", () => { if (!o.off) choose(o.v); });
        return opt;
      }));
      if (hl >= 0) active.input.setAttribute("aria-activedescendant", `${id}-o${hl}`);
      else active.input.removeAttribute("aria-activedescendant");
      // 해당 칸 바로 아래에 띄우고, 화면 오른쪽 밖으로 나가면 왼쪽으로 당긴다
      list.style.left = `${active.box.offsetLeft}px`;
      const over = list.getBoundingClientRect().right - (document.documentElement.clientWidth - 8);
      if (over > 0) list.style.left = `${active.box.offsetLeft - over}px`;
    }

    function open(s) {
      if (active && active !== s) active.input.setAttribute("aria-expanded", "false");
      active = s;
      opts = choices(s);
      hl = opts.findIndex((o) => o.v === num(s));
      list.hidden = false;
      s.input.setAttribute("aria-expanded", "true");
      render();
    }

    function close() {
      if (!active) return;
      list.hidden = true;
      active.input.setAttribute("aria-expanded", "false");
      active.input.removeAttribute("aria-activedescendant");
      active = null;
    }

    function setVal(s, v) { s.input.value = v ? String(v) : ""; }

    // 일이 그달 말일보다 크면 말일로 맞춘다 (2월 31일 → 2월 28일)
    function fix() {
      const y = num(Y), m = num(M), d = num(D);
      if (d && m >= 1 && m <= 12) {
        const n = daysIn(y || 2024, m);
        if (d > n) setVal(D, n);
      }
      segs.forEach((s) => s.box.classList.remove("is-invalid"));
    }

    function next(s) {
      fix();
      const i = segs.indexOf(s);
      if (i < 2) segs[i + 1].input.focus();
      else close();
    }

    function choose(v) {
      const s = active;
      setVal(s, v);
      next(s);
    }

    function fillAll(text) {
      const m = text.trim().match(/^(\d{4})\D?(\d{1,2})\D?(\d{1,2})$/);
      if (!m) return false;
      setVal(Y, Number(m[1])); setVal(M, Number(m[2])); setVal(D, Number(m[3]));
      fix();
      D.input.focus();
      close();
      return true;
    }

    segs.forEach((s) => {
      s.input.addEventListener("focus", () => { open(s); s.input.select(); });
      s.input.addEventListener("click", () => { if (active !== s) open(s); });

      s.input.addEventListener("input", () => {
        const digits = s.input.value.replace(/\D/g, "").slice(0, s.len);
        s.input.value = digits;
        s.box.classList.remove("is-invalid");
        if (active !== s) open(s);
        opts = choices(s);
        hl = digits ? opts.findIndex((o) => o.v === Number(digits)) : -1;
        if (hl < 0 && digits && s === Y) hl = opts.findIndex((o) => String(o.v).startsWith(digits));
        render();
        // 연도 4자리, 월 2자리(또는 2~9), 일 2자리(또는 4~9)가 되면 다음 칸으로
        const n = Number(digits);
        if (digits.length >= s.len || (s !== Y && digits.length === 1 && n > (s === M ? 1 : 3))) next(s);
      });

      s.input.addEventListener("paste", (e) => {
        if (fillAll(e.clipboardData.getData("text"))) e.preventDefault();  // "2015-08-01" 붙여넣기
      });

      s.input.addEventListener("keydown", (e) => {
        if (e.isComposing) return;
        const move = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: s.cols, ArrowUp: -s.cols }[e.key];
        if (move !== undefined) {
          if (active !== s) {
            if (e.key === "ArrowDown") { e.preventDefault(); open(s); }
            return;
          }
          e.preventDefault();
          let i = hl < 0 ? 0 : Math.min(Math.max(hl + move, 0), opts.length - 1);
          hl = i;
          render();
          return;
        }
        if (e.key === "Enter" && active === s && hl >= 0) {
          e.preventDefault();  // 목록이 열려 있을 때 Enter는 고르기 (폼 제출 아님)
          if (!opts[hl].off) choose(opts[hl].v);
          return;
        }
        if (e.key === "Escape" && active) { e.preventDefault(); close(); return; }
        if (e.key === "Backspace" && !s.input.value && s !== Y) { e.preventDefault(); segs[segs.indexOf(s) - 1].input.focus(); return; }
        if (["-", ".", "/", " "].includes(e.key)) { e.preventDefault(); if (s.input.value) next(s); }
      });
    });

    // 날짜 칸 바깥으로 포커스가 나가면 목록을 닫는다
    root.addEventListener("focusout", (e) => {
      if (!root.contains(e.relatedTarget)) { close(); fix(); }
    });

    // 각 칸이 올바른지: 비었거나 범위를 벗어나면 false
    function valid(s) {
      const v = num(s);
      if (!s.input.value) return false;
      if (s === Y) return v >= 1900 && v <= maxY;
      if (s === M) return v >= 1 && v <= 12;
      return v >= 1 && v <= daysIn(num(Y) || 2024, num(M) >= 1 && num(M) <= 12 ? num(M) : 1);
    }

    return {
      first: Y.input,
      // edge: "start"면 비어 있는 월/일을 1월 1일로, "end"면 12월 말일로 채운다
      get(edge) {
        const filled = segs.map((s) => Boolean(s.input.value));
        if (!filled[0]) return filled[1] || filled[2] ? null : "";
        if (!edge && (!filled[1] || !filled[2])) return null;
        if (segs.some((s, i) => filled[i] && !valid(s))) return null;
        const y = num(Y);
        const mm = num(M) || (edge === "end" ? 12 : 1);
        const dd = num(D) || (edge === "end" ? daysIn(y, mm) : 1);
        return `${y}-${pad2(mm)}-${pad2(dd)}`;
      },
      set(iso) {
        const [y, m, d] = iso ? iso.split("-").map(Number) : [0, 0, 0];
        setVal(Y, y); setVal(M, m); setVal(D, d);
        fix();
      },
      markInvalid() {
        const bad = segs.filter((s) => !valid(s));
        bad.forEach((s) => s.box.classList.add("is-invalid"));
        (bad[0] || Y).input.focus();
      },
    };
  }

  const dates = {};

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
    loadStats(range, { force });
    try {
      if (force || !state.seriesCache[range]) state.seriesCache[range] = await API.series(range);
      if (state.range !== range) return;  // 그사이 다른 기간을 눌렀으면 그리지 않는다
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
    const ma = series.ma20 || [];
    const maValues = ma.filter((v) => v !== null);
    const hi = Math.max(...values, ...maValues), lo = Math.min(...values, ...maValues);
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
    if (state.showMa && maValues.length) {
      // 20일 이동평균: 값이 없는 앞부분(None)은 건너뛰고 이어서 그린다
      let started = false;
      const md = ma.map((v, i) => {
        if (v === null) return "";
        const cmd = started ? "L" : "M";
        started = true;
        return `${cmd}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
      }).join(" ");
      root.append(svg("path", { class: "chart-ma", d: md }));
    }
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
        ...(state.showMa && s.ma20 && s.ma20[i] !== null ? [el("small", { text: `20일 평균 ${won(s.ma20[i])}원` })] : []),
        ...(event ? [el("em", { text: event.title })] : []),
      );
      tip.hidden = false;
      tip.style.left = `${ratio * 100}%`;
      tip.dataset.flip = String(ratio > 0.7);
    });
    chart.addEventListener("pointerleave", () => { tip.hidden = true; guide.hidden = true; });
  }

  /* ── 3-2. 기간 통계 ───────────────────────── */
  const RANGE_NAMES = { "3m": "최근 3개월", "1y": "최근 1년", "5y": "최근 5년", all: "전체" };
  const signed = (n, digits = 1) => `${n > 0 ? "+" : ""}${Number(n).toFixed(digits)}`;

  async function loadStats(range, { force = false } = {}) {
    try {
      if (force || !state.statsCache[range]) state.statsCache[range] = await API.statistics(range);
      if (state.range === range) renderStats(state.statsCache[range]);
    } catch (err) {
      $("stats-range").textContent = `통계를 불러오지 못했어요. ${err.message}`;
    }
  }

  function gapText(ma) {
    if (!ma) return "데이터가 모자라요";
    if (Math.abs(ma.gap_pct) < 0.05) return "지금과 거의 같아요";
    return ma.gap_pct > 0 ? `지금이 ${ma.gap_pct.toFixed(1)}% 높아요` : `지금이 ${Math.abs(ma.gap_pct).toFixed(1)}% 낮아요`;
  }

  function renderStats(st) {
    $("stats-range").textContent = `${RANGE_NAMES[st.range]}, ${st.start} – ${st.end} (${st.count.toLocaleString("ko-KR")}영업일)`;
    $("st-change").textContent = `${signed(st.change_pct)}%`;
    $("st-change-sub").textContent = st.change_pct < 0 ? "기간 동안 엔화가 싸졌어요" : "기간 동안 엔화가 비싸졌어요";
    $("st-ma20").textContent = st.ma20 ? won(st.ma20.value) : "—";
    $("st-ma20-sub").textContent = gapText(st.ma20);
    $("st-ma60").textContent = st.ma60 ? won(st.ma60.value) : "—";
    $("st-ma60-sub").textContent = gapText(st.ma60);
    $("st-vol").textContent = st.volatility_pct === null ? "—" : `${st.volatility_pct.toFixed(1)}%`;
    $("st-vol-sub").textContent = st.volatility_20d_pct === null ? "" : `최근 20일은 ${st.volatility_20d_pct.toFixed(1)}%`;
    $("st-p5").textContent = `하위 ${Math.round(st.percentile_5y)}%`;
    $("st-p5-sub").textContent = `최근 1년 중에서는 하위 ${Math.round(st.percentile_1y)}%`;
    drawMonthly(st);
    renderYearly(st.yearly);
  }

  // 월별 평균: 기간 평균(점선)보다 비싼 달은 위로, 싼 달은 아래로
  function drawMonthly(st) {
    const months = st.monthly;
    const bars = $("monthly-bars");
    const tip = $("monthly-tip");
    bars.replaceChildren();
    tip.hidden = true;
    bars.style.setProperty("--gap", months.length > 60 ? "1px" : "2px");
    const maxAbs = Math.max(...months.map((m) => Math.abs(m.diff_pct)), 0.5);

    months.forEach((m, i) => {
      const up = m.diff_pct >= 0;
      const label = `${m.month} 평균 ${won(m.average)}원, 기간 평균보다 ${signed(m.diff_pct)}%`;
      const col = el("div", { class: "mbar-col", tabindex: "0", "aria-label": label });
      const bar = el("span", { class: `mbar mbar--${up ? "up" : "down"}` });
      bar.style.height = `${(Math.abs(m.diff_pct) / maxAbs) * 48}%`;
      col.append(bar);
      const show = () => {
        const ratio = (i + 0.5) / months.length;
        tip.replaceChildren(
          el("span", { text: m.month }),
          el("strong", { text: `${won(m.average)}원` }),
          el("small", { text: `기간 평균보다 ${signed(m.diff_pct)}% (${up ? "비싼 달" : "싼 달"})` }),
        );
        tip.hidden = false;
        tip.style.left = `${ratio * 100}%`;
        tip.dataset.flip = String(ratio > 0.6);
      };
      col.addEventListener("pointerenter", show);
      col.addEventListener("focus", show);
      col.addEventListener("pointerleave", () => { tip.hidden = true; });
      col.addEventListener("blur", () => { tip.hidden = true; });
      bars.append(col);
    });

    const axis = $("monthly-axis");
    axis.replaceChildren();
    const picks = months.length > 2 ? [0, Math.floor((months.length - 1) / 2), months.length - 1] : months.map((_, i) => i);
    picks.forEach((i) => {
      axis.append(el("span", { text: months[i].month.replace("-", "."), style: `left: ${((i + 0.5) / months.length) * 100}%` }));
    });

    const cheapest = months.reduce((a, b) => (b.diff_pct < a.diff_pct ? b : a));
    const dearest = months.reduce((a, b) => (b.diff_pct > a.diff_pct ? b : a));
    $("monthly-plot").setAttribute(
      "aria-label",
      `월별 평균 ${months.length}개월. 가장 싼 달 ${cheapest.month} (${signed(cheapest.diff_pct)}%), 가장 비싼 달 ${dearest.month} (${signed(dearest.diff_pct)}%). 아래 연도별 표에서 숫자를 볼 수 있어요.`,
    );
  }

  function renderYearly(years) {
    const rows = $("yearly-rows");
    rows.replaceChildren();
    [...years].reverse().forEach((y) => {
      rows.append(el("tr", {}, [
        el("td", { text: String(y.year) }),
        el("td", { class: "num", text: won(y.average) }),
        el("td", { class: "num", text: `${won(y.max.value)} (${y.max.date.slice(5)})` }),
        el("td", { class: "num", text: `${won(y.min.value)} (${y.min.date.slice(5)})` }),
        el("td", { class: `num ${y.change_pct >= 0 ? "up" : "down"}`, text: `${signed(y.change_pct)}%` }),
      ]));
    });
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
    const date = dates.add.get();
    if (!date) {
      dates.add.markInvalid();
      toast("날짜를 확인해 주세요. 연도, 월, 일을 모두 넣어야 해요.", "error");
      return;
    }
    if (date > todayLocal()) {
      toast("오늘 이후 날짜는 추가할 수 없어요.", "error");
      return;
    }
    const body = { date, value: Number(form.value.value), memo: form.memo.value };
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
    state.statsCache = {};
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

  /* ── 다크 모드 ───────────────────────── */
  // 처음에는 시스템 설정을 따르고, 버튼으로 바꾸면 이 브라우저에 기억한다
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const currentTheme = () => document.documentElement.dataset.theme || (systemDark.matches ? "dark" : "light");

  function paintThemeButton() {
    const dark = currentTheme() === "dark";
    $("theme-toggle").setAttribute("aria-pressed", String(dark));
    $("theme-label").textContent = dark ? "라이트 모드" : "다크 모드";
    $("theme-toggle").setAttribute("aria-label", dark ? "밝은 화면으로 바꾸기" : "어두운 화면으로 바꾸기");
  }

  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* 저장이 막힌 브라우저는 이번 방문에만 적용 */ }
    paintThemeButton();
  }

  /* ── 이벤트 연결 ───────────────────────── */
  function bindEvents() {
    $("theme-toggle").addEventListener("click", toggleTheme);
    systemDark.addEventListener("change", paintThemeButton);
    paintThemeButton();
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
    $("ma-toggle").addEventListener("change", (e) => {
      state.showMa = e.target.checked;
      if (state.series) drawChart(state.series);
    });
    window.addEventListener("resize", () => { if (state.series) drawChart(state.series); });

    $("add-form").addEventListener("submit", addData);
    $("filter-toggle").addEventListener("click", () => {
      const form = $("filter-form");
      form.hidden = !form.hidden;
      $("filter-toggle").setAttribute("aria-expanded", String(!form.hidden));
      if (!form.hidden) dates.start.first.focus();
    });
    $("filter-form").addEventListener("submit", (e) => {
      e.preventDefault();
      // 연도만 고르면 그해 전체, 연도와 월만 고르면 그달 전체를 조회한다
      const start = dates.start.get("start");
      const end = dates.end.get("end");
      if (start === null || end === null) {
        (start === null ? dates.start : dates.end).markInvalid();
        toast("기간 날짜를 확인해 주세요. 연도부터 넣어야 하고, 13월 같은 없는 날짜는 쓸 수 없어요.", "error");
        return;
      }
      if (start && end && start > end) {
        toast("시작일이 종료일보다 늦어요. 날짜를 다시 골라 주세요.", "error");
        return;
      }
      state.filter = { start, end };
      loadData({ reset: true });
    });
    $("filter-reset").addEventListener("click", () => {
      dates.start.set("");
      dates.end.set("");
      state.filter = { start: "", end: "" };
      loadData({ reset: true });
    });
    $("more-btn").addEventListener("click", () => loadData());
    $("export-csv").addEventListener("click", () => exportData("csv"));
    $("export-json").addEventListener("click", () => exportData("json"));
  }

  /* ── 시작 ───────────────────────── */
  async function init() {
    dates.add = dateSelect($("add-date"));
    dates.start = dateSelect($("filter-start"));
    dates.end = dateSelect($("filter-end"));
    dates.add.set(todayLocal());
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
