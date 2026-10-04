import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function assetUrl(path) {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;

  if (/^https?:\/\//i.test(API_BASE)) {
    return new URL(path, API_BASE).toString();
  }

  return path;
}

function scoreLabel(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatDateTime(value) {
  if (!value) return "미입력";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

function StatusPill({ status }) {
  const online = status === "online";
  return (
    <span className={`status-pill ${online ? "online" : ""}`}>
      <span className="status-dot" />
      {online ? "Backend 연결됨" : "Backend 확인 중"}
    </span>
  );
}

function Metric({ label, value }) {
  const numeric = value === null || value === undefined ? null : Number(value);
  const width = numeric === null ? 0 : Math.max(0, Math.min(100, numeric * 100));

  return (
    <div className="metric">
      <div className="metric-head">
        <span>{label}</span>
        <strong>{scoreLabel(value)}</strong>
      </div>
      <div className="metric-track" aria-hidden="true">
        <div className="metric-fill" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function CandidateCard({ candidate, onSelect }) {
  const image = assetUrl(candidate.image_url);

  return (
    <button className="candidate-card" type="button" onClick={() => onSelect(candidate)}>
      <div className="candidate-image-wrap">
        {image ? (
          <img className="candidate-image" src={image} alt={candidate.category || "습득물"} />
        ) : (
          <div className="image-placeholder">No Image</div>
        )}
        <span className="score-badge">{scoreLabel(candidate.matching_score)}</span>
      </div>
      <div className="candidate-body">
        <strong>{candidate.category || "분류 미지정"}</strong>
        <span>{[candidate.color, candidate.brand].filter(Boolean).join(" · ") || "상세 정보 없음"}</span>
        <span>{candidate.location || "장소 미입력"}</span>
      </div>
    </button>
  );
}

function MatchDashboard({ candidate, onClose }) {
  if (!candidate) return null;

  const image = assetUrl(candidate.image_url);

  return (
    <section className="dashboard-panel" aria-label="Match Dashboard">
      <div className="section-title-row">
        <div>
          <span className="eyebrow">MATCH DASHBOARD</span>
          <h2>추천 후보 상세 비교</h2>
        </div>
        <button className="ghost-button" type="button" onClick={onClose}>
          닫기
        </button>
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-item-card">
          {image ? (
            <img src={image} alt={candidate.category || "후보 물품"} />
          ) : (
            <div className="image-placeholder large">No Image</div>
          )}
          <div>
            <span className="eyebrow">CANDIDATE #{candidate.id}</span>
            <h3>{candidate.category || "분류 미지정"}</h3>
            <p>{candidate.description || "등록된 설명이 없습니다."}</p>
          </div>
        </div>

        <div className="score-summary">
          <span className="eyebrow">MATCHING SCORE</span>
          <strong>{scoreLabel(candidate.matching_score)}</strong>
          <span>
            이미지 유사도는 DINOv2 Embedding을 사용하며, 텍스트·위치·시간 점수를 함께 반영합니다.
          </span>
        </div>
      </div>

      <div className="metric-list">
        <Metric label="이미지 유사도" value={candidate.image_similarity} />
        <Metric label="텍스트 유사도" value={candidate.text_similarity} />
        <Metric label="위치 적합도" value={candidate.location_score} />
        <Metric label="시간 적합도" value={candidate.time_score} />
      </div>

      <div className="dashboard-meta">
        <div>
          <span>색상</span>
          <strong>{candidate.color || "미입력"}</strong>
        </div>
        <div>
          <span>브랜드</span>
          <strong>{candidate.brand || "미입력"}</strong>
        </div>
        <div>
          <span>습득 장소</span>
          <strong>{candidate.location || "미입력"}</strong>
        </div>
        <div>
          <span>습득 시간</span>
          <strong>{formatDateTime(candidate.occurred_at)}</strong>
        </div>
      </div>
    </section>
  );
}

function RegisterView({ onGoSearch }) {
  const [form, setForm] = useState({
    category: "",
    color: "",
    brand: "",
    description: "",
    location: "",
    occurredAt: "",
  });
  const [image, setImage] = useState(null);
  const [preview, setPreview] = useState(null);
  const [state, setState] = useState({ loading: false, message: "", error: false });
  const [analysis, setAnalysis] = useState({ loading: false, message: "", error: false });

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleImage(file) {
    setImage(file || null);
    setPreview(file ? URL.createObjectURL(file) : null);
    setAnalysis({ loading: false, message: "", error: false });

    if (!file) return;

    const body = new FormData();
    body.append("image", file);
    setAnalysis({ loading: true, message: "AI가 사진을 분석하고 있습니다...", error: false });

    try {
      const response = await fetch(apiUrl("/items/analyze"), {
        method: "POST",
        body,
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "AI 분석 중 오류가 발생했습니다.");
      }

      setForm((current) => ({
        ...current,
        category: data.category || current.category,
        color: data.color || current.color,
        brand: data.brand || current.brand,
        description: data.features || data.description || current.description,
      }));

      setAnalysis({
        loading: false,
        message: "AI 분석 결과를 자동 입력했습니다. 필요한 부분은 직접 수정할 수 있습니다.",
        error: false,
      });
    } catch (error) {
      setAnalysis({
        loading: false,
        message: error.message,
        error: true,
      });
    }
  }

  async function submit(event) {
    event.preventDefault();

    if (!image) {
      setState({ loading: false, message: "습득물 사진을 선택해주세요.", error: true });
      return;
    }

    const body = new FormData();
    body.append("item_type", "found");
    body.append("image", image);

    if (form.category) body.append("category", form.category);
    if (form.color) body.append("color", form.color);
    if (form.brand) body.append("brand", form.brand);
    if (form.description) body.append("description", form.description);
    if (form.location) body.append("location", form.location);
    if (form.occurredAt) body.append("occurred_at", form.occurredAt);

    setState({ loading: true, message: "", error: false });

    try {
      const response = await fetch(apiUrl("/items"), { method: "POST", body });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "등록 중 오류가 발생했습니다.");
      }

      setState({
        loading: false,
        message: `습득물 #${data.id} 등록이 완료되었습니다.`,
        error: false,
      });
    } catch (error) {
      setState({ loading: false, message: error.message, error: true });
    }
  }

  return (
    <section className="workspace">
      <div className="section-heading">
        <span className="eyebrow">FOUND ITEM</span>
        <h1>습득물 간편 등록</h1>
        <p>
          습득물 사진을 선택하면 Vision-Language 모델이 물품 종류, 색상, 브랜드/로고,
          외형적 특징을 자동 추출합니다. 사용자는 자동 입력된 내용을 확인·수정한 뒤 등록합니다.
        </p>
      </div>

      <form className="form-layout" onSubmit={submit}>
        <div className="upload-panel">
          <Field label="습득물 사진">
            <input
              className="file-input"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => handleImage(event.target.files?.[0])}
            />
          </Field>

          <div className="preview-box">
            {preview ? <img src={preview} alt="선택한 습득물 미리보기" /> : <span>사진 미리보기</span>}
          </div>

          <div className="integration-note">
            <strong>{analysis.loading ? "Vision/VLM 분석 중..." : "AI 자동 정보 추출"}</strong>
            <span>
              사진을 선택하면 물품 종류 · 색상 · 브랜드/로고 · 외형적 특징을 자동 분석하여
              오른쪽 입력란에 채웁니다.
            </span>
          </div>

          {analysis.message ? (
            <div className={`form-message ${analysis.error ? "error" : "success"}`}>
              {analysis.message}
            </div>
          ) : null}
        </div>

        <div className="form-panel">
          <div className="two-column">
            <Field label="물품 종류">
              <input
                value={form.category}
                onChange={(event) => updateField("category", event.target.value)}
                placeholder="예: 무선 이어폰 케이스"
              />
            </Field>
            <Field label="색상">
              <input
                value={form.color}
                onChange={(event) => updateField("color", event.target.value)}
                placeholder="예: 검은색"
              />
            </Field>
          </div>

          <Field label="브랜드 / 로고">
            <input
              value={form.brand}
              onChange={(event) => updateField("brand", event.target.value)}
              placeholder="예: Samsung"
            />
          </Field>

          <Field label="외형적 특징 / 설명">
            <textarea
              rows="4"
              value={form.description}
              onChange={(event) => updateField("description", event.target.value)}
              placeholder="예: 오른쪽 모서리에 작은 흠집이 있음"
            />
          </Field>

          <div className="two-column">
            <Field label="습득 장소">
              <input
                value={form.location}
                onChange={(event) => updateField("location", event.target.value)}
                placeholder="예: 공과대학 1층"
              />
            </Field>
            <Field label="습득 시간">
              <input
                type="datetime-local"
                value={form.occurredAt}
                onChange={(event) => updateField("occurredAt", event.target.value)}
              />
            </Field>
          </div>

          {state.message ? (
            <div className={`form-message ${state.error ? "error" : "success"}`}>{state.message}</div>
          ) : null}

          <div className="form-actions">
            <button className="primary-button" type="submit" disabled={state.loading}>
              {state.loading ? "등록 중..." : "습득물 등록"}
            </button>
            <button className="secondary-button" type="button" onClick={onGoSearch}>
              바로 검색해보기
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}

function SearchView() {
  const [form, setForm] = useState({
    description: "",
    location: "",
    occurredAt: "",
    topK: 5,
  });
  const [image, setImage] = useState(null);
  const [preview, setPreview] = useState(null);
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [state, setState] = useState({ loading: false, message: "", error: false });

  const hasQuery = useMemo(
    () => Boolean(form.description.trim() || image || form.location.trim() || form.occurredAt),
    [form, image]
  );

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleImage(file) {
    setImage(file || null);
    setPreview(file ? URL.createObjectURL(file) : null);
  }

  async function submit(event) {
    event.preventDefault();

    if (!hasQuery) {
      setState({
        loading: false,
        message: "사진, 자연어 설명, 장소 또는 시간 중 하나 이상을 입력해주세요.",
        error: true,
      });
      return;
    }

    const body = new FormData();
    if (form.description) body.append("description", form.description);
    if (form.location) body.append("location", form.location);
    if (form.occurredAt) body.append("occurred_at", form.occurredAt);
    if (image) body.append("image", image);
    body.append("top_k", "5");

    setState({ loading: true, message: "", error: false });
    setSelected(null);

    try {
      const response = await fetch(apiUrl("/search"), { method: "POST", body });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "검색 중 오류가 발생했습니다.");
      }

      setResults(data.results || []);
      setState({
        loading: false,
        message:
          data.results?.length > 0
            ? `${data.results.length}개의 후보를 찾았습니다.`
            : "등록된 습득물 후보가 없습니다.",
        error: false,
      });
    } catch (error) {
      setResults([]);
      setState({ loading: false, message: error.message, error: true });
    }
  }

  return (
    <section className="workspace">
      <div className="section-heading">
        <span className="eyebrow">LOST ITEM</span>
        <h1>사진 또는 자연어로 검색</h1>
        <p>
          이미지·텍스트·장소·시간 정보를 함께 입력할수록 더 많은 검색 신호를 활용할 수 있습니다.
        </p>
      </div>

      <form className="search-panel" onSubmit={submit}>
        <div className="search-main">
          <Field label="자연어 설명">
            <textarea
              rows="3"
              value={form.description}
              onChange={(event) => updateField("description", event.target.value)}
              placeholder="예: 어제 오후 공대에서 검은색 갤럭시 버즈 케이스를 잃어버렸어요."
            />
          </Field>

          <div className="two-column">
            <Field label="분실 추정 장소">
              <input
                value={form.location}
                onChange={(event) => updateField("location", event.target.value)}
                placeholder="예: 공과대학 1층"
              />
            </Field>
            <Field label="분실 추정 시간">
              <input
                type="datetime-local"
                value={form.occurredAt}
                onChange={(event) => updateField("occurredAt", event.target.value)}
              />
            </Field>
          </div>
        </div>

        <div className="search-side">
          <Field label="분실물 사진 (선택)">
            <input
              className="file-input"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => handleImage(event.target.files?.[0])}
            />
          </Field>

          <div className="search-preview">
            {preview ? <img src={preview} alt="검색할 분실물 미리보기" /> : <span>선택한 사진</span>}
          </div>

          <div className="integration-note">
            <strong>검색 결과</strong>
            <span>중간발표 데모는 매칭 점수가 높은 Top-5 후보를 표시합니다.</span>
          </div>

          <button className="primary-button full" type="submit" disabled={state.loading}>
            {state.loading ? "검색 중..." : "유사 후보 검색"}
          </button>
        </div>
      </form>

      {state.message ? (
        <div className={`form-message search-message ${state.error ? "error" : "success"}`}>
          {state.message}
        </div>
      ) : null}

      {results.length > 0 ? (
        <section className="results-section">
          <div className="section-title-row">
            <div>
              <span className="eyebrow">TOP-5 RESULTS</span>
              <h2>유사 습득물 후보</h2>
            </div>
            <span className="demo-badge">DINOv2 + metadata ranking</span>
          </div>

          <div className="candidate-grid">
            {results.map((candidate) => (
              <CandidateCard key={candidate.id} candidate={candidate} onSelect={setSelected} />
            ))}
          </div>
        </section>
      ) : null}

      <MatchDashboard candidate={selected} onClose={() => setSelected(null)} />
    </section>
  );
}

export default function App() {
  const [view, setView] = useState("home");
  const [backendStatus, setBackendStatus] = useState("checking");

  useEffect(() => {
    let active = true;

    fetch(apiUrl("/"))
      .then((response) => {
        if (!response.ok) throw new Error("backend offline");
        return response.json();
      })
      .then(() => {
        if (active) setBackendStatus("online");
      })
      .catch(() => {
        if (active) setBackendStatus("offline");
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" type="button" onClick={() => setView("home")}>
          <span className="brand-mark">F</span>
          <span>
            <strong>FindYU</strong>
            <small>AI Lost & Found Matching</small>
          </span>
        </button>

        <nav className="nav-actions" aria-label="주요 메뉴">
          <button className={view === "register" ? "active" : ""} type="button" onClick={() => setView("register")}>
            습득물 등록
          </button>
          <button className={view === "search" ? "active" : ""} type="button" onClick={() => setView("search")}>
            분실물 검색
          </button>
          <StatusPill status={backendStatus} />
        </nav>
      </header>

      <main>
        {view === "home" ? (
          <section className="hero">
            <div className="hero-copy">
              <span className="eyebrow">FIND YOUR LOST ITEM, WITH AI</span>
              <h1>
                사진 한 장과 자연어로
                <br />
                잃어버린 물건을 더 빠르게.
              </h1>
              <p>
                FindYU는 습득자의 등록 부담을 줄이고, 분실자에게 이미지·텍스트·장소·시간 정보를
                결합한 Top-K 후보를 제공합니다.
              </p>
              <div className="hero-actions">
                <button className="primary-button" type="button" onClick={() => setView("register")}>
                  습득물 등록하기
                </button>
                <button className="secondary-button" type="button" onClick={() => setView("search")}>
                  분실물 검색하기
                </button>
              </div>
            </div>

            <div className="hero-flow">
              <div className="flow-step">
                <span>01</span>
                <strong>등록</strong>
                <p>사진 업로드 후 정보 확인</p>
              </div>
              <div className="flow-line" />
              <div className="flow-step">
                <span>02</span>
                <strong>검색</strong>
                <p>사진·자연어 기반 후보 탐색</p>
              </div>
              <div className="flow-line" />
              <div className="flow-step">
                <span>03</span>
                <strong>판단</strong>
                <p>Match Dashboard에서 직접 확인</p>
              </div>
            </div>
          </section>
        ) : null}

        {view === "register" ? <RegisterView onGoSearch={() => setView("search")} /> : null}
        {view === "search" ? <SearchView /> : null}
      </main>

      <footer className="footer">
        <span>2026-2 AI 서비스 프로젝트 · FindYU</span>
        <span>Midterm Demo MVP</span>
      </footer>
    </div>
  );
}
