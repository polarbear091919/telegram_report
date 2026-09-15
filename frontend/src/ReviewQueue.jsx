import React, { useEffect, useState } from "react";
import {
  Check,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  SkipForward,
} from "lucide-react";
import { api, fmt } from "./api";

const reasons = [
  ["foreign", "해외 상장사"],
  ["fund", "펀드 · ETF"],
  ["digital", "디지털자산"],
  ["private", "비상장사"],
  ["ir_self", "기업 IR 자료"],
];
function initialSession() {
  try {
    return JSON.parse(sessionStorage.getItem("research:review")) || {};
  } catch {
    return {};
  }
}
const show = (v) => (Array.isArray(v) ? v.join(", ") || "—" : v || "—");
function PdfPreview({ id }) {
  const [info, setInfo] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api(`/review/${id}/preview`, { signal: controller.signal })
      .then(setInfo)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [id]);
  return (
    <div className="review-preview">
      {error ? (
        <p role="alert">
          미리보기를 불러오지 못했습니다. 원문 PDF를 확인해 주세요.
        </p>
      ) : !info ? (
        <p role="status">원문 미리보기를 준비하고 있습니다…</p>
      ) : (
        <>
          <p>
            전체 {info.page_count}페이지 · 첫 {info.preview_pages}페이지
            미리보기
          </p>
          {Array.from({ length: info.preview_pages }, (_, i) => (
            <figure key={i}>
              <img
                src={`/api/review/${id}/pages/${i + 1}`}
                alt={`검토 보고서 ${i + 1}페이지`}
                loading={i ? "lazy" : "eager"}
                onError={() => setError("preview failed")}
              />
              <figcaption>
                {i + 1} / {info.page_count}
              </figcaption>
            </figure>
          ))}
        </>
      )}
    </div>
  );
}
export default function ReviewQueue({ onChanged }) {
  const [session, setSession] = useState(initialSession),
    [data, setData] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [reload, setReload] = useState(0),
    [reason, setReason] = useState("foreign");
  const skipped = session.skipped || [],
    counts = session.counts || { verify: 0, oos: 0, retag: 0 };
  useEffect(() => {
    sessionStorage.setItem("research:review", JSON.stringify(session));
  }, [session]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const q = new URLSearchParams();
    skipped.forEach((id) => q.append("skipped", id));
    api(`/review?${q}`, { signal: controller.signal })
      .then((x) => {
        setData(x);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [reload, JSON.stringify(skipped)]);
  const row = data?.report;
  async function act(action) {
    if (busy || !row) return;
    setBusy(true);
    setError("");
    try {
      const result = await api(`/review/${row.id}/action`, {
        method: "POST",
        body: JSON.stringify({
          action,
          reason: action === "oos" ? reason : null,
        }),
      });
      setSession((s) => ({
        ...s,
        counts: { ...counts, [action]: counts[action] + 1 },
        last: { ...result, action },
      }));
      setReload((x) => x + 1);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function skip() {
    setSession((s) => ({
      ...s,
      skipped: [...skipped, row.id],
      last: { action: "skip", report_id: row.id },
    }));
  }
  async function undo() {
    if (!session.last || busy) return;
    setBusy(true);
    setError("");
    try {
      const last = session.last;
      if (last.action !== "skip")
        await api(`/review/undo/${last.undo_token}`, { method: "POST" });
      setSession((s) => ({
        ...s,
        last: null,
        skipped: skipped.filter((id) => id !== last.report_id),
        counts:
          last.action === "skip"
            ? counts
            : {
                ...counts,
                [last.action]: Math.max(0, counts[last.action] - 1),
              },
      }));
      setReload((x) => x + 1);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="review-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">REVIEW & REFINE</span>
          <h1>리포트 검토</h1>
          <p className="page-description">
            원문과 분류 결과를 함께 확인하고, 검토가 필요한 리포트를 정리하세요.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => setReload((x) => x + 1)}
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </div>
      <div className="review-summary">
        <span>
          검토 대기 <strong>{fmt(data?.remaining)}</strong>
        </span>
        <span>
          승인 <strong>{counts.verify}</strong>
        </span>
        <span>
          대상 제외 <strong>{counts.oos}</strong>
        </span>
        <span>
          재태깅 대기 <strong>{counts.retag}</strong>
        </span>
        <span>
          건너뜀 <strong>{skipped.length}</strong>
        </span>
        <button
          className="text-button"
          disabled={!session.last || busy}
          onClick={undo}
        >
          <RotateCcw size={13} />
          마지막 작업 되돌리기
        </button>
      </div>
      {error && (
        <div className="error-panel" role="alert">
          <p>{error}</p>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => setReload((x) => x + 1)}
          >
            다시 불러오기
          </button>
        </div>
      )}
      {loading ? (
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" />
          <h3>검토할 리포트를 불러오는 중입니다</h3>
        </div>
      ) : !row ? (
        <div className="review-empty panel">
          <Check size={34} />
          <h2>
            {data?.remaining
              ? "이번 검토에서 모두 건너뛰었습니다"
              : "검토 대기열이 비었습니다"}
          </h2>
          <p>
            {skipped.length
              ? "건너뛴 보고서를 다시 불러와 검토를 이어갈 수 있습니다."
              : "새로운 검토 대상이 들어오면 여기에 표시됩니다."}
          </p>
          {skipped.length > 0 && (
            <button
              className="button secondary"
              onClick={() => setSession((s) => ({ ...s, skipped: [] }))}
            >
              건너뛴 보고서 다시 보기
            </button>
          )}
        </div>
      ) : (
        <div className="review-grid">
          <section className="panel review-pdf">
            <header>
              <div>
                <span className="eyebrow">SOURCE DOCUMENT</span>
                <h3>{row.title || row.file_name}</h3>
              </div>
              <a
                className="button secondary"
                href={row.pdf_url}
                target="_blank"
                rel="noreferrer"
              >
                원문 PDF <ExternalLink size={14} />
              </a>
            </header>
            <PdfPreview key={row.id} id={row.id} />
          </section>
          <section className="panel review-inspector">
            <div className="review-reason">
              <span>검토가 필요한 이유</span>
              <p>{row.tagging_notes || "분류 결과 확인 필요"}</p>
            </div>
            <h3>
              분류 결과 <small>#{row.id}</small>
            </h3>
            <dl>
              {[
                ["보고서 유형", row.report_type],
                ["발행처", row.publisher],
                ["발행처 유형", row.publisher_type],
                ["분류 신뢰도", row.tagging_confidence],
              ].map(([l, v]) => (
                <React.Fragment key={l}>
                  <dt>{l}</dt>
                  <dd>{show(v)}</dd>
                </React.Fragment>
              ))}
            </dl>
            <h4>기업 매핑</h4>
            <dl>
              {[
                ["종목코드 · 원문", row.stock_codes_raw],
                ["종목코드 · KRX", row.stock_codes],
                ["기업명 · 원문", row.company_names_raw],
                ["기업명 · KRX", row.company_names],
                ["산업(대)", row.sectors_major],
                ["산업(중)", row.sectors_minor],
                ["제품", row.products],
              ].map(([l, v]) => (
                <React.Fragment key={l}>
                  <dt>{l}</dt>
                  <dd>{show(v)}</dd>
                </React.Fragment>
              ))}
            </dl>
            <details className="review-metadata">
              <summary>원본 메시지 정보</summary>
              <p>{row.file_name}</p>
              <p>{row.sent_at}</p>
              <p>{row.caption || "캡션 없음"}</p>
            </details>
            <div className="review-actions">
              <button
                className="button primary"
                disabled={busy}
                onClick={() => act("verify")}
              >
                <Check size={15} />
                분류 승인
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={skip}
              >
                <SkipForward size={15} />
                건너뛰기
              </button>
              <label>
                분석 대상 제외 사유
                <select
                  aria-label="분석 대상 제외 사유"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                >
                  {reasons.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="button subtle-warning"
                disabled={busy}
                onClick={() => act("oos")}
              >
                선택한 사유로 대상 제외
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => act("retag")}
              >
                <RotateCcw size={14} />
                재태깅 대기열로 이동
              </button>
              <p>
                재태깅은 다음 태깅 작업에서 처리됩니다. 이 버튼은 지금 LLM을
                호출하지 않습니다.
              </p>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
