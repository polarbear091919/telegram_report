import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BarChart3,
  Download,
  LoaderCircle,
  RefreshCw,
  Search,
} from "lucide-react";
import { api, downloadCSV, fmt, periods, units } from "./api";

const colors = [
  "#4b8469",
  "#5a7ca5",
  "#bb9861",
  "#8b78a8",
  "#689ba1",
  "#b07775",
  "#92a85e",
  "#a48c7a",
  "#849bb6",
  "#658779",
];
function PeriodControls({ days, setDays, unit, setUnit }) {
  return (
    <div className="coverage-controls">
      <select
        aria-label="통계 기간"
        value={days}
        onChange={(e) => setDays(Number(e.target.value))}
      >
        {periods.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
      <select
        aria-label="집계 단위"
        value={unit}
        onChange={(e) => setUnit(e.target.value)}
      >
        {units.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </div>
  );
}
export function SeriesChart({ rows, seriesKey, unit, title }) {
  const [hidden, setHidden] = useState([]);
  const prepared = useMemo(() => {
    const names = [
      ...new Set(rows.map((r) => (seriesKey ? r[seriesKey] : "리포트"))),
    ];
    const dates = [...new Set(rows.map((r) => r.bucket.slice(0, 10)))].sort();
    if (!dates.length) return { names, buckets: [], values: {} };
    const buckets = [];
    const cursor = new Date(`${dates[0]}T00:00:00Z`),
      end = new Date(`${dates.at(-1)}T00:00:00Z`);
    while (cursor <= end) {
      buckets.push(cursor.toISOString().slice(0, 10));
      if (unit === "M") cursor.setUTCMonth(cursor.getUTCMonth() + 1);
      else cursor.setUTCDate(cursor.getUTCDate() + (unit === "W" ? 7 : 1));
    }
    const values = Object.fromEntries(names.map((n) => [n, new Map()]));
    rows.forEach((r) =>
      values[seriesKey ? r[seriesKey] : "리포트"].set(
        r.bucket.slice(0, 10),
        r.count,
      ),
    );
    return { names, buckets, values };
  }, [rows, seriesKey, unit]);
  const { names, buckets, values } = prepared;
  const shown = names.filter((n) => !hidden.includes(n));
  const max = Math.max(1, ...shown.flatMap((n) => [...values[n].values()]));
  const x = (i) =>
      48 + (buckets.length === 1 ? 320 : (i / (buckets.length - 1)) * 640),
    y = (value) => 226 - (value / max) * 185;
  if (!rows.length)
    return (
      <div className="chart-empty">
        <BarChart3 size={26} />
        <p>이 기간에 집계할 리포트가 없습니다.</p>
        <small>기간을 넓히거나 선택한 분류를 바꿔보세요.</small>
      </div>
    );
  return (
    <div className="series-chart">
      <svg viewBox="0 0 720 265" role="img" aria-label={title}>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line
              x1="48"
              x2="688"
              y1={y(max * f)}
              y2={y(max * f)}
              stroke="#edf0f3"
            />
            <text
              x="37"
              y={y(max * f) + 4}
              textAnchor="end"
              fill="#95a3ad"
              fontSize="10"
            >
              {fmt(Math.round(max * f))}
            </text>
          </g>
        ))}
        {shown.map((name) => (
          <g key={name}>
            <polyline
              fill="none"
              stroke={colors[names.indexOf(name) % colors.length]}
              strokeWidth="2"
              strokeLinejoin="round"
              points={buckets
                .map((b, i) => `${x(i)},${y(values[name].get(b) || 0)}`)
                .join(" ")}
            />
            {buckets.map(
              (b, i) =>
                values[name].get(b) > 0 && (
                  <circle
                    key={b}
                    cx={x(i)}
                    cy={y(values[name].get(b))}
                    r={buckets.length > 100 ? 1.7 : 3}
                    fill={colors[names.indexOf(name) % colors.length]}
                  >
                    <title>
                      {b} · {name}: {fmt(values[name].get(b))}건
                    </title>
                  </circle>
                ),
            )}
          </g>
        ))}
        {buckets
          .filter(
            (_, i) =>
              i === 0 ||
              i === buckets.length - 1 ||
              i % Math.max(1, Math.ceil(buckets.length / 5)) === 0,
          )
          .map((b) => (
            <text
              key={b}
              x={x(buckets.indexOf(b))}
              y="252"
              textAnchor="middle"
              fill="#95a3ad"
              fontSize="10"
            >
              {b.slice(2).replaceAll("-", ".")}
            </text>
          ))}
      </svg>
      <div className="chart-legend">
        {names.map((n, i) => (
          <button
            key={n}
            aria-pressed={!hidden.includes(n)}
            className={hidden.includes(n) ? "muted-legend" : ""}
            onClick={() =>
              setHidden((s) =>
                s.includes(n) ? s.filter((x) => x !== n) : [...s, n],
              )
            }
          >
            <i style={{ background: colors[i % colors.length] }} />
            {n}
          </button>
        ))}
      </div>
      <details className="chart-data">
        <summary>집계 데이터 보기</summary>
        <button
          className="text-button"
          onClick={() => downloadCSV(rows, `${title}.csv`)}
        >
          <Download size={12} />
          CSV 내려받기
        </button>
        <div className="data-scroll">
          <table>
            <thead>
              <tr>
                <th>기간</th>
                <th>구분</th>
                <th>건수</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.bucket.slice(0, 10)}</td>
                  <td>{seriesKey ? r[seriesKey] : "리포트"}</td>
                  <td>{fmt(r.count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
export function StockActivity({ code }) {
  const [days, setDays] = useState(36500),
    [unit, setUnit] = useState("W"),
    [data, setData] = useState(null),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    api(`/stocks/${code}/activity?days=${days}&unit=${unit}`, {
      signal: controller.signal,
    })
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [code, days, unit, retry]);
  return (
    <section className="activity-section">
      <div className="activity-heading">
        <div>
          <span className="eyebrow">COVERAGE HISTORY</span>
          <h2>기업 리서치 흐름</h2>
          <p>이 기업으로 분류된 모든 리포트 · 본문에서만 언급된 종목은 제외</p>
        </div>
        <PeriodControls {...{ days, setDays, unit, setUnit }} />
      </div>
      {error ? (
        <div className="error-panel">
          {error}
          <button
            className="text-button"
            onClick={() => setRetry((x) => x + 1)}
          >
            다시 시도
          </button>
        </div>
      ) : !data ? (
        <div className="comparison-loading">
          <LoaderCircle className="spin" size={17} />
          발행 추이를 불러오는 중입니다.
        </div>
      ) : (
        <div className="activity-grid">
          <div className="panel chart-panel">
            <h3>
              발행 추이 <small>{fmt(data.total)}건</small>
            </h3>
            <SeriesChart
              rows={data.timeline}
              unit={unit}
              title="기업 발행 추이"
            />
          </div>
          <div className="panel publisher-panel">
            <h3>발행처 분포</h3>
            <p>상위 5개 발행처와 기타</p>
            {data.publishers.length ? (
              data.publishers.map((r, i) => (
                <div className="publisher-bar" key={r.publisher}>
                  <div>
                    <span>{r.publisher}</span>
                    <strong>
                      {fmt(r.count)} <small>건</small>
                    </strong>
                  </div>
                  <div className="bar-track">
                    <i
                      style={{
                        width: `${(r.count / Math.max(...data.publishers.map((p) => p.count))) * 100}%`,
                        background: colors[i % colors.length],
                      }}
                    />
                  </div>
                </div>
              ))
            ) : (
              <p className="muted">이 기간의 발행 기록이 없습니다.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
export default function Coverage({ onStock }) {
  const [days, setDays] = useState(36500),
    [unit, setUnit] = useState("W"),
    [level, setLevel] = useState("sectors_major"),
    [items, setItems] = useState([]),
    [oos, setOos] = useState(false),
    [tab, setTab] = useState("coverage"),
    [search, setSearch] = useState("");
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    const q = new URLSearchParams({
      days,
      unit,
      level,
      include_oos: tab === "types" && oos,
    });
    items.forEach((x) => q.append("items", x));
    api(`/market?${q}`, { signal: controller.signal })
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [days, unit, level, items, oos, retry, tab]);
  return (
    <section className="market-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">RESEARCH LANDSCAPE</span>
          <h1>리서치 커버리지</h1>
          <p className="page-description">
            산업과 기업을 연결해, 리서치가 쌓이는 흐름을 읽어보세요.
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => setRetry((x) => x + 1)}
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </div>
      <div className="coverage-toolbar">
        <div className="market-tabs">
          {[
            ["coverage", "산업 · 제품 커버리지"],
            ["types", "리포트 유형별 발행량"],
          ].map(([v, l]) => (
            <button
              key={v}
              className={tab === v ? "active" : ""}
              onClick={() => setTab(v)}
            >
              {l}
            </button>
          ))}
        </div>
        <PeriodControls {...{ days, setDays, unit, setUnit }} />
      </div>
      {tab === "coverage" ? (
        <div className="sector-toolbar">
          <div className="segmented">
            {[
              ["sectors_major", "산업(대)"],
              ["sectors_minor", "산업(중)"],
              ["products", "제품"],
            ].map(([v, l]) => (
              <button
                key={v}
                className={level === v ? "active" : ""}
                onClick={() => {
                  setLevel(v);
                  setItems([]);
                }}
              >
                {l}
              </button>
            ))}
          </div>
          <details className="sector-picker">
            <summary>
              분류 선택{" "}
              {items.length ? `· ${items.length}개` : "· 발행량 상위 10개"}
            </summary>
            <div>
              <label>
                <Search size={13} />
                <input
                  aria-label="분류 검색"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="산업 또는 제품 검색"
                />
              </label>
              <button className="text-button" onClick={() => setItems([])}>
                선택 해제 · 상위 10개 보기
              </button>
              {[...new Set([...(data?.available_items || []), ...items])]
                .filter((x) => x.includes(search))
                .map((x) => (
                  <label key={x}>
                    <input
                      type="checkbox"
                      checked={items.includes(x)}
                      onChange={() =>
                        setItems((s) =>
                          s.includes(x) ? s.filter((v) => v !== x) : [...s, x],
                        )
                      }
                    />
                    {x}
                  </label>
                ))}
            </div>
          </details>
          <span className="muted">
            선택한 분류로 기업 순위도 함께 좁힙니다.
          </span>
        </div>
      ) : (
        <label className="oos-toggle">
          <input
            type="checkbox"
            checked={oos}
            onChange={(e) => setOos(e.target.checked)}
          />
          분석 대상 외 자료 포함{" "}
          <span>IR · 해외 · 펀드 · 디지털자산 · 비상장</span>
        </label>
      )}
      {error ? (
        <div className="error-panel">
          <p>{error}</p>
          <button
            className="button secondary"
            onClick={() => setRetry((x) => x + 1)}
          >
            다시 시도
          </button>
        </div>
      ) : !data ? (
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" />
          <h3>리서치 발행 기록을 집계하고 있습니다</h3>
          <p>처음 조회할 때는 잠시 걸릴 수 있습니다.</p>
        </div>
      ) : (
        <>
          <div className="stats-grid">
            <div className="stat">
              <span>기간 내 리포트</span>
              <div>
                <strong>
                  {fmt(tab === "coverage" ? data.inscope : data.total)}
                </strong>
                <small>건</small>
              </div>
              <p>분류 완료된 저장 리포트 기준</p>
            </div>
            <div className="stat">
              <span>발행처</span>
              <div>
                <strong>{fmt(data.publishers)}</strong>
                <small>곳</small>
              </div>
              <p>선택한 기간 기준</p>
            </div>
            <div className="stat">
              <span>
                {tab === "coverage" ? "산업 · 제품 분류" : "분석 대상 외"}
              </span>
              <div>
                <strong>
                  {fmt(
                    tab === "coverage" ? data.available_items.length : data.oos,
                  )}
                </strong>
                <small>{tab === "coverage" ? "개" : "건"}</small>
              </div>
              <p>
                {tab === "coverage"
                  ? "선택한 분류 수준 기준"
                  : oos
                    ? "대상 외 자료 포함 중"
                    : "대상 외 자료 제외 중"}
              </p>
            </div>
            <div className="stat">
              <span>최근 리포트</span>
              <div>
                <strong className="date-stat">
                  {data.latest?.replaceAll("-", ".") || "—"}
                </strong>
              </div>
              <p>
                {data.earliest
                  ? `${data.earliest}부터 집계`
                  : "선택한 기간의 기록 없음"}
              </p>
            </div>
          </div>
          {tab === "coverage" ? (
            <div className="coverage-grid">
              <section className="panel chart-panel">
                <div className="chart-heading">
                  <h3>산업 · 제품별 발행 흐름</h3>
                  <span>단위: 건</span>
                </div>
                <SeriesChart
                  rows={data.coverage}
                  seriesKey="sector"
                  unit={unit}
                  title="산업 제품 커버리지"
                />
              </section>
              <section className="panel ranking-panel">
                <h3>
                  자주 다뤄진 기업 <small>TOP 20</small>
                </h3>
                <p>수집 채널의 발행 횟수 기준</p>
                {data.ranking.map((r, i) => (
                  <button key={r.code} onClick={() => onStock(r.code)}>
                    <span className="rank-index">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span>
                      {r.name || r.code}
                      <small>{r.code}</small>
                    </span>
                    <strong>{fmt(r.count)}</strong>
                    <ArrowUpRight size={13} />
                  </button>
                ))}
                {!data.ranking.length && (
                  <p className="chart-empty">일치하는 기업이 없습니다.</p>
                )}
              </section>
            </div>
          ) : (
            <section className="panel chart-panel">
              <div className="chart-heading">
                <h3>리포트 유형별 발행 흐름</h3>
                <span>단위: 건</span>
              </div>
              <SeriesChart
                rows={data.types}
                seriesKey="report_type"
                unit={unit}
                title="리포트 유형별 발행량"
              />
            </section>
          )}
          <p className="coverage-footnote">
            수집된 리포트의 발행 빈도입니다. 시장 거래량이나 투자 선호도 지표가
            아닙니다. 분석 대상 외 자료는 게시일이 없으면 텔레그램 발송일(한국
            시간)로 집계합니다.
          </p>
        </>
      )}
    </section>
  );
}
