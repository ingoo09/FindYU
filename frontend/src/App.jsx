import { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";
const MAX_REGISTER_IMAGES = 5; // 백엔드 gemini_analyzer.MAX_IMAGES와 같게 유지

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

function CandidateCard({ candidate, labels = {}, onSelect }) {
  const image = assetUrl(candidate.image_url);
  // 체크한 항목 중 습득물 쪽 값을 몰라서 거르지 못한 항목
  const unknown = Object.entries(candidate.filter_check || {})
    .filter(([, result]) => result === "미확인")
    .map(([key]) => labels[key] || key);

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
        {unknown.length ? <span className="filter-unknown">확인 필요: {unknown.join(", ")}</span> : null}
      </div>
    </button>
  );
}

function MatchDashboard({ candidate, labels = {}, onClose }) {
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
            이미지 유사도는 DINOv2, 자연어-이미지 유사도는 SigLIP2를 사용하며 위치·시간 점수를 함께 반영합니다.
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
        {Object.entries(candidate.form_values || {}).map(([key, value]) => (
          <div key={key}>
            <span>
              {labels[key] || key}
              {candidate.field_sources?.[key] === "human" ? " (직접 입력)" : ""}
            </span>
            <strong>{value}</strong>
          </div>
        ))}
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

// ---------------------------------------------------------
// 품목별 체크 폼 (GET /form-schema). 등록·검색 화면이 같은 항목을 쓴다.
// "모르겠음" = 답하지 않음 (등록: AI 값 사용 / 검색: 그 항목으로 거르지 않음)
// ---------------------------------------------------------
const UNKNOWN = "모르겠음";

function useFormSchema() {
  const [schema, setSchema] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetch(apiUrl("/form-schema"))
      .then((response) => {
        if (!response.ok) throw new Error("form-schema");
        return response.json();
      })
      .then((data) => {
        if (active) setSchema(data);
      })
      .catch(() => {
        if (active) setError("체크 항목을 불러오지 못했습니다. 백엔드 연결을 확인해주세요.");
      });
    return () => {
      active = false;
    };
  }, []);

  return [schema, error];
}

function fieldsFor(schema, category) {
  if (!schema || !category || category === UNKNOWN) return [];
  return schema.forms?.[category] || [];
}

function emptyAnswers(schema, category = UNKNOWN) {
  const answers = { category };
  fieldsFor(schema, category).forEach((field) => {
    answers[field.key] = UNKNOWN;
  });
  return answers;
}

function fieldLabelMap(schema) {
  const map = { category: "품목" };
  Object.values(schema?.forms || {}).forEach((fields) =>
    fields.forEach((field) => {
      map[field.key] = field.label;
    })
  );
  return map;
}

function ChipGroup({ label, options, value, aiValue, onSelect }) {
  return (
    <div className="chip-group" role="radiogroup" aria-label={label}>
      {options.map((option) => {
        const selected = value === option;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={selected}
            className={`chip ${selected ? "selected" : ""} ${option === UNKNOWN ? "unknown" : ""}`}
            onClick={() => onSelect(option)}
          >
            {option}
            {aiValue === option && option !== UNKNOWN ? <span className="chip-ai">AI</span> : null}
          </button>
        );
      })}
    </div>
  );
}

// fields: [{key, label, type, options, help}], ai: {key: {ai_value, needs_check, check_reasons, suggestions}}
function CheckFields({ fields, values, onChange, ai = {}, touched = {} }) {
  return (
    <div className="check-fields">
      {fields.map((field) => {
        const info = ai[field.key];
        const highlight = Boolean(info?.needs_check) && !touched[field.key];
        const value = values[field.key] ?? UNKNOWN;
        const hint = highlight && info.check_reasons?.length ? info.check_reasons.join(" · ") : field.help;

        return (
          <div key={field.key} className={`check-field ${highlight ? "needs-check" : ""}`}>
            <div className="check-field-head">
              <span className="field-label">{field.label}</span>
              {highlight ? <span className="check-badge">확인해주세요</span> : null}
              {touched[field.key] && info ? <span className="check-done">직접 선택</span> : null}
            </div>

            {field.type === "text" ? (
              <>
                <input
                  className="check-text"
                  value={value === UNKNOWN ? "" : value}
                  placeholder="모르면 비워 두세요"
                  onChange={(event) => onChange(field.key, event.target.value.trim() ? event.target.value : UNKNOWN)}
                />
                <ChipGroup
                  label={`${field.label} 후보`}
                  options={[...new Set([...(info?.suggestions || []), UNKNOWN])]}
                  value={value}
                  aiValue={info?.ai_value}
                  onSelect={(option) => onChange(field.key, option)}
                />
              </>
            ) : (
              <ChipGroup
                label={field.label}
                options={field.options}
                value={value}
                aiValue={info?.ai_value}
                onSelect={(option) => onChange(field.key, option)}
              />
            )}

            {hint ? <span className="field-hint">{hint}</span> : null}
          </div>
        );
      })}
    </div>
  );
}

function RegisteredItemStatus({ item, labels }) {
  if (item.status === "analyzing") {
    return (
      <div className="form-message success">
        습득물 #{item.id}: AI가 사진을 분석하고 있습니다. 페이지를 나가도 분석이 끝나면 자동으로 등록됩니다.
      </div>
    );
  }

  if (item.status === "analysis_failed") {
    return (
      <div className="form-message error">
        습득물 #{item.id}은 등록되었지만 AI 자동 분석에 실패했습니다. 사진 검색은 그대로 가능합니다.
      </div>
    );
  }

  const filled = Object.entries(item.form_values || {}).filter(([, value]) => value && value !== UNKNOWN);

  return (
    <div className="form-message success">
      습득물 #{item.id} 등록 완료:{" "}
      {filled.map(([key, value]) => `${labels[key] || key} ${value}`).join(" · ") || "항목 정보 없음"}
    </div>
  );
}

function imagesKeyOf(images) {
  // 대표 사진만 바꾸는 것은 같은 사진 묶음으로 본다 (서버도 순서와 무관하게 비교)
  return images
    .map((item) => `${item.file.name}:${item.file.size}:${item.file.lastModified}`)
    .sort()
    .join("|");
}

function RegisterView({ onGoSearch }) {
  const [schema, schemaError] = useFormSchema();
  const schemaRef = useRef(null);
  schemaRef.current = schema;
  const [form, setForm] = useState({ description: "", location: "", occurredAt: "" });
  // 첫 번째 사진이 대표 사진(검색 기준). 나머지는 AI 분석에 함께 사용된다.
  const [images, setImages] = useState([]); // [{ file, url }]
  const [answers, setAnswers] = useState({ category: UNKNOWN });
  const [touched, setTouched] = useState({});
  const touchedRef = useRef({});
  const [analysis, setAnalysis] = useState({ status: "idle", data: null, imagesKey: "" });
  const [state, setState] = useState({ loading: false, message: "", error: false });
  const [registered, setRegistered] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);

  const imagesKey = useMemo(() => imagesKeyOf(images), [images]);
  const labels = useMemo(() => fieldLabelMap(schema), [schema]);
  const checkForm = analysis.status === "done" ? analysis.data.check_form : null;
  const aiCategory = checkForm?.category.ai_value;

  // AI 값은 현재 품목이 AI가 고른 품목일 때만 항목에 표시한다
  const aiInfo = useMemo(() => {
    if (!checkForm) return {};
    const info = { category: checkForm.category };
    if (answers.category === aiCategory) {
      checkForm.fields.forEach((field) => {
        info[field.key] = field;
      });
    }
    return info;
  }, [checkForm, aiCategory, answers.category]);

  function markTouched(key) {
    touchedRef.current = { ...touchedRef.current, [key]: true };
    setTouched(touchedRef.current);
  }

  function resetChecks() {
    touchedRef.current = {};
    setTouched({});
    setAnswers({ category: UNKNOWN });
    setAnalysis({ status: "idle", data: null, imagesKey: "" });
  }

  // 사진이 바뀌면 잠시 뒤 AI 분석을 요청하고, 결과로 체크 폼을 미리 채운다 (사람이 고른 항목은 유지)
  useEffect(() => {
    if (!images.length) {
      setAnalysis({ status: "idle", data: null, imagesKey: "" });
      return undefined;
    }

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setAnalysis({ status: "loading", data: null, imagesKey });
      const body = new FormData();
      body.append("image", images[0].file);
      images.slice(1).forEach((item) => body.append("extra_images", item.file));

      try {
        const response = await fetch(apiUrl("/items/analyze"), {
          method: "POST",
          body,
          signal: controller.signal,
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "AI 분석에 실패했습니다.");

        setAnalysis({ status: "done", data, imagesKey });
        const form = data.check_form;
        setAnswers((current) => {
          const done = touchedRef.current;
          const category = done.category ? current.category : form.category.ai_value;
          const next = { category };
          const aiFields = category === form.category.ai_value ? form.fields : [];
          fieldsFor(schemaRef.current, category).forEach((field) => {
            const ai = aiFields.find((item) => item.key === field.key);
            next[field.key] = done[field.key] ? current[field.key] ?? UNKNOWN : ai?.ai_value ?? UNKNOWN;
          });
          return next;
        });
      } catch (error) {
        if (error.name === "AbortError") return;
        setAnalysis({ status: "error", data: null, imagesKey, message: error.message });
      }
    }, 900);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // 사진 묶음이 바뀔 때만 다시 분석한다 (대표 사진 순서 변경은 제외)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imagesKey]);

  // 등록 후 이 화면에 남아 있는 동안만 분석 결과를 확인한다.
  // 화면을 나가도 서버에서 분석은 계속되고 결과는 자동으로 등록된다.
  useEffect(() => {
    if (!registered || registered.status !== "analyzing") return undefined;

    const timer = setTimeout(async () => {
      try {
        const response = await fetch(apiUrl(`/items/${registered.id}`));
        if (response.ok) setRegistered(await response.json());
      } catch {
        // 일시적인 네트워크 오류는 다음 확인 때 다시 시도
        setRegistered((current) => ({ ...current }));
      }
    }, 3000);

    return () => clearTimeout(timer);
  }, [registered]);

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function changeAnswer(key, value) {
    markTouched(key);
    if (key !== "category") {
      setAnswers((current) => ({ ...current, [key]: value }));
      return;
    }

    // 품목을 바꾸면 그 품목의 항목으로 바꾼다. 공통 항목(색상 등)과 직접 고른 값은 유지
    setAnswers((current) => {
      const next = { category: value };
      const aiFields = checkForm && value === aiCategory ? checkForm.fields : [];
      fieldsFor(schema, value).forEach((field) => {
        const ai = aiFields.find((item) => item.key === field.key);
        if (touchedRef.current[field.key] && current[field.key] !== undefined) next[field.key] = current[field.key];
        else if (ai) next[field.key] = ai.ai_value;
        else next[field.key] = current[field.key] ?? UNKNOWN;
      });
      return next;
    });
  }

  function addImages(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;

    const isDuplicate = (file) =>
      images.some((item) => item.file.name === file.name && item.file.size === file.size);
    const fresh = files.filter((file) => !isDuplicate(file));
    const room = MAX_REGISTER_IMAGES - images.length;
    const accepted = fresh.slice(0, Math.max(0, room));

    if (fresh.length > accepted.length) {
      setState({
        loading: false,
        message: `사진은 최대 ${MAX_REGISTER_IMAGES}장까지 등록할 수 있습니다.`,
        error: true,
      });
    }

    setImages([...images, ...accepted.map((file) => ({ file, url: URL.createObjectURL(file) }))]);
    // 같은 파일을 다시 고를 수 있도록 input 초기화
    setFileInputKey((key) => key + 1);
  }

  function removeImage(index) {
    setImages((current) => {
      URL.revokeObjectURL(current[index].url);
      return current.filter((_, i) => i !== index);
    });
  }

  function makePrimary(index) {
    setImages((current) => [current[index], ...current.filter((_, i) => i !== index)]);
  }

  function clearImages() {
    images.forEach((item) => URL.revokeObjectURL(item.url));
    setImages([]);
  }

  function buildFormAnswers(useAnalysis) {
    // AI 분석을 쓰는 경우: 사람이 직접 고른 항목만 보낸다 (나머지는 서버가 AI 값으로 채움)
    // AI 분석이 없는 경우: 선택된 값은 모두 사람이 고른 값이다
    const keys = ["category", ...fieldsFor(schema, answers.category).map((field) => field.key)];
    const result = {};
    keys.forEach((key) => {
      const value = answers[key];
      if (!value || value === UNKNOWN) return;
      if (useAnalysis && !touched[key]) return;
      result[key] = value;
    });
    // 항목은 품목별로 다르므로, 품목을 AI에 맡기지 않는 경우 품목을 함께 보낸다
    if (!useAnalysis && Object.keys(result).length && !result.category) return {};
    return result;
  }

  async function submit(event) {
    event.preventDefault();

    if (!images.length) {
      setState({ loading: false, message: "습득물 사진을 선택해주세요.", error: true });
      return;
    }

    const useAnalysis = analysis.status === "done" && analysis.imagesKey === imagesKey;
    const body = new FormData();
    body.append("item_type", "found");
    body.append("image", images[0].file);
    images.slice(1).forEach((item) => body.append("extra_images", item.file));
    if (useAnalysis) body.append("analysis_id", analysis.data.analysis_id);

    const formAnswers = buildFormAnswers(useAnalysis);
    if (Object.keys(formAnswers).length) body.append("form_answers", JSON.stringify(formAnswers));
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
        message: `습득물 #${data.id} 등록이 완료되었습니다. 이 페이지를 나가셔도 됩니다.`,
        error: false,
      });
      setRegistered(data);
      setForm({ description: "", location: "", occurredAt: "" });
      clearImages();
      resetChecks();
      setFileInputKey((key) => key + 1);
    } catch (error) {
      setState({ loading: false, message: error.message, error: true });
    }
  }

  const categoryField = schema?.category_field;
  const formFields = fieldsFor(schema, answers.category);
  const needsCheckCount = Object.entries(aiInfo).filter(
    ([key, info]) => info?.needs_check && !touched[key]
  ).length;

  return (
    <section className="workspace">
      <div className="section-heading">
        <span className="eyebrow">FOUND ITEM</span>
        <h1>습득물 간편 등록</h1>
        <p>
          사진을 올리면 AI가 항목을 미리 골라 둡니다. 노란색 "확인해주세요" 항목만 보고 고쳐 주세요.
          그대로 등록해도 됩니다.
        </p>
      </div>

      <form className="form-layout" onSubmit={submit}>
        <div className="upload-panel">
          <Field
            label={`습득물 사진 (${images.length}/${MAX_REGISTER_IMAGES})`}
            hint="휴대폰은 후면·전면·측면을 함께 올리면 기종을 더 정확히 구분합니다. 첫 번째 사진이 대표 사진입니다."
          >
            <input
              key={fileInputKey}
              className="file-input"
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp"
              disabled={images.length >= MAX_REGISTER_IMAGES}
              onChange={(event) => addImages(event.target.files)}
            />
          </Field>

          <div className="preview-box">
            {images.length ? (
              <img src={images[0].url} alt="대표 사진 미리보기" />
            ) : (
              <span>사진 미리보기</span>
            )}
          </div>

          {images.length ? (
            <ul className="thumb-list" aria-label="선택한 사진">
              {images.map((item, index) => (
                <li key={item.url} className={`thumb ${index === 0 ? "primary" : ""}`}>
                  <img src={item.url} alt={`선택한 사진 ${index + 1}`} />
                  {index === 0 ? <span className="thumb-badge">대표</span> : null}
                  <div className="thumb-actions">
                    {index !== 0 ? (
                      <button type="button" onClick={() => makePrimary(index)}>
                        대표로
                      </button>
                    ) : null}
                    <button type="button" onClick={() => removeImage(index)} aria-label={`사진 ${index + 1} 삭제`}>
                      삭제
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}

          {analysis.status === "done" && analysis.data.photo_hint ? (
            <div className="photo-hint">
              <strong>사진 추가 안내</strong>
              <span>{analysis.data.photo_hint}</span>
            </div>
          ) : null}

          <div className="integration-note">
            <strong>AI 자동 정보 추출</strong>
            <span>
              {analysis.status === "loading"
                ? "AI가 사진을 분석하고 있습니다... 기다리지 않고 등록해도 등록 후 자동으로 분석합니다."
                : analysis.status === "done"
                  ? needsCheckCount
                    ? `AI가 항목을 골라 두었습니다. 확인이 필요한 항목 ${needsCheckCount}개를 봐 주세요.`
                    : "AI가 항목을 골라 두었습니다. 다르면 고쳐 주세요."
                  : analysis.status === "error"
                    ? `AI 분석 실패: ${analysis.message} 항목을 직접 고르거나 그대로 등록하면 등록 후 다시 분석합니다.`
                    : "사진을 올리면 AI가 품목·색상·브랜드 등을 미리 골라 둡니다. 직접 고른 값이 AI 값보다 우선합니다."}
            </span>
          </div>

          {registered ? <RegisteredItemStatus item={registered} labels={labels} /> : null}
        </div>

        <div className="form-panel">
          {schemaError ? <div className="form-message error">{schemaError}</div> : null}

          {categoryField ? (
            <CheckFields
              fields={[categoryField]}
              values={answers}
              onChange={changeAnswer}
              ai={aiInfo}
              touched={touched}
            />
          ) : null}

          {formFields.length ? (
            <CheckFields fields={formFields} values={answers} onChange={changeAnswer} ai={aiInfo} touched={touched} />
          ) : null}

          <Field label="외형적 특징 / 설명">
            <textarea
              rows="3"
              value={form.description}
              onChange={(event) => updateField("description", event.target.value)}
              placeholder="비워 두면 AI가 관찰한 특징으로 채웁니다. 예: 오른쪽 모서리에 작은 흠집"
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
  const [schema, schemaError] = useFormSchema();
  const [form, setForm] = useState({
    description: "",
    location: "",
    occurredAt: "",
    topK: 5,
  });
  const [answers, setAnswers] = useState({ category: UNKNOWN });
  const [image, setImage] = useState(null);
  const [preview, setPreview] = useState(null);
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [state, setState] = useState({ loading: false, message: "", error: false });

  const labels = useMemo(() => fieldLabelMap(schema), [schema]);
  const formFields = fieldsFor(schema, answers.category);
  const filters = useMemo(() => {
    const result = {};
    formFields.forEach((field) => {
      const value = answers[field.key];
      if (value && value !== UNKNOWN) result[field.key] = value;
    });
    return result;
  }, [answers, formFields]);
  const hasCategory = answers.category && answers.category !== UNKNOWN;

  const hasQuery = useMemo(
    () =>
      Boolean(
        form.description.trim() || image || form.location.trim() || form.occurredAt || hasCategory
      ),
    [form, image, hasCategory]
  );

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function changeAnswer(key, value) {
    if (key === "category") {
      // 품목을 바꾸면 공통 항목(색상 등)만 유지
      setAnswers((current) => {
        const next = emptyAnswers(schema, value);
        Object.keys(next).forEach((k) => {
          if (k !== "category" && current[k] !== undefined) next[k] = current[k];
        });
        return next;
      });
      return;
    }
    setAnswers((current) => ({ ...current, [key]: value }));
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
        message: "품목, 사진, 자연어 설명, 장소 또는 시간 중 하나 이상을 입력해주세요.",
        error: true,
      });
      return;
    }

    const body = new FormData();
    if (form.description) body.append("description", form.description);
    if (form.location) body.append("location", form.location);
    if (form.occurredAt) body.append("occurred_at", form.occurredAt);
    if (image) body.append("image", image);
    if (hasCategory) {
      body.append("category", answers.category);
      if (Object.keys(filters).length) body.append("filters", JSON.stringify(filters));
    }
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
      const filtered =
        data.total_found_items !== undefined && data.total_candidates < data.total_found_items
          ? ` (체크한 항목으로 ${data.total_found_items}건 중 ${data.total_candidates}건으로 좁힘)`
          : "";
      setState({
        loading: false,
        message:
          data.results?.length > 0
            ? `${data.results.length}개의 후보를 찾았습니다.${filtered}`
            : `조건에 맞는 습득물 후보가 없습니다.${filtered}`,
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
          확실히 아는 항목만 체크하세요. 체크한 항목이 다른 습득물은 빼고, 나머지는 사진·설명 유사도로
          순위를 매깁니다. 모르는 항목은 "모르겠음"으로 두면 됩니다.
        </p>
      </div>

      <form className="search-panel" onSubmit={submit}>
        <div className="search-main">
          {schemaError ? <div className="form-message error">{schemaError}</div> : null}
          {schema ? (
            <CheckFields fields={[schema.category_field]} values={answers} onChange={changeAnswer} />
          ) : null}
          {formFields.length ? (
            <CheckFields fields={formFields} values={answers} onChange={changeAnswer} />
          ) : null}

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
            <span>체크한 항목과 다른 습득물은 제외하고, 매칭 점수가 높은 Top-5 후보를 표시합니다.</span>
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
            <span className="demo-badge">체크 항목 필터 + DINOv2 + SigLIP2 + metadata</span>
          </div>

          <div className="candidate-grid">
            {results.map((candidate) => (
              <CandidateCard key={candidate.id} candidate={candidate} labels={labels} onSelect={setSelected} />
            ))}
          </div>
        </section>
      ) : null}

      <MatchDashboard candidate={selected} labels={labels} onClose={() => setSelected(null)} />
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
