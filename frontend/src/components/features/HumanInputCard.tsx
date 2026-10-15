import { useState, type KeyboardEvent } from "react";
import type {
  HumanInputField,
  HumanInputOption,
  HumanInputRequest,
  HumanInputResponse,
} from "@/lib/humanInput";
import {
  buildHumanInputFormSubmissionValue,
  createHumanInputOptionResponse,
  createHumanInputTextResponse,
} from "@/lib/humanInput";

type FormValue = string | boolean | string[];

type Props = {
  request: HumanInputRequest;
  disabled?: boolean;
  pending?: boolean;
  answeredResponse?: HumanInputResponse | null;
  onSubmit?: (response: HumanInputResponse) => void | Promise<void>;
};

function initialFormValues(fields: HumanInputField[]): Record<string, FormValue> {
  const values: Record<string, FormValue> = {};
  for (const field of fields) {
    if (field.type === "checkbox") values[field.name] = false;
    if (field.type === "multi_select") values[field.name] = [];
  }
  return values;
}

export function HumanInputCard({
  request,
  disabled = false,
  pending = false,
  answeredResponse = null,
  onSubmit,
}: Props) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [composing, setComposing] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, FormValue>>(
    () => initialFormValues(request.fields ?? []),
  );
  const interactive = Boolean(onSubmit) && !answeredResponse;
  const isDisabled = disabled || pending || Boolean(answeredResponse) || !onSubmit;
  const isForm = request.input_mode === "form" && (request.fields?.length ?? 0) > 0;
  const allowText =
    !isForm
    && (request.input_mode === "free_text"
      || request.input_mode === "choice_with_other"
      || !request.options?.length);
  const options = request.options ?? [];
  const showOptions =
    !isForm
    && (request.input_mode === "single_choice" || request.input_mode === "choice_with_other")
    && options.length > 0;
  /** choice_with_other：其它回答默认折叠，贴近官方 Human Input Card */
  const otherCollapsed = showOptions && request.input_mode === "choice_with_other";

  const submit = async (response: HumanInputResponse) => {
    if (isDisabled || !onSubmit) return;
    setError("");
    await onSubmit(response);
    if (response.response_kind === "text") setText("");
  };

  const handleOption = (option: HumanInputOption) => {
    void submit(createHumanInputOptionResponse(request, option));
  };

  const handleTextSubmit = () => {
    const value = text.trim();
    if (!value) {
      setError("请输入内容后再提交");
      return;
    }
    void submit(createHumanInputTextResponse(request, value));
  };

  const handleFormSubmit = () => {
    const missing = (request.fields ?? []).filter((field) => {
      if (!field.required) return false;
      const value = formValues[field.name];
      if (typeof value === "string") return !value.trim();
      if (Array.isArray(value)) return value.length === 0;
      return value === undefined;
    });
    if (missing.length > 0) {
      setError("请填写必填项");
      return;
    }
    const value = buildHumanInputFormSubmissionValue(request, formValues);
    if (!value.trim()) {
      setError("请至少填写一项");
      return;
    }
    void submit(createHumanInputTextResponse(request, value));
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    if (e.nativeEvent.isComposing || composing || e.keyCode === 229) return;
    e.preventDefault();
    handleTextSubmit();
  };

  const status = answeredResponse
    ? "已回答"
    : pending
      ? "提交中…"
      : null;

  const setField = (name: string, value: FormValue) => {
    setFormValues((prev) => ({ ...prev, [name]: value }));
    if (error) setError("");
  };

  const textEditor = (
    <div className="human-input-text">
      <textarea
        value={text}
        disabled={isDisabled}
        placeholder={showOptions ? "自由补充…" : "在此回答…"}
        rows={2}
        onChange={(e) => {
          setText(e.target.value);
          if (error) setError("");
        }}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={() => setComposing(false)}
        onKeyDown={handleKeyDown}
      />
      <div className="human-input-actions">
        {error ? <span className="human-input-error">{error}</span> : (
          <span className="human-input-hint-inline">Enter 提交 · Shift+Enter 换行</span>
        )}
        <button
          type="button"
          className="human-input-submit"
          disabled={isDisabled || !text.trim()}
          onClick={handleTextSubmit}
        >
          {pending ? "提交中…" : "提交"}
        </button>
      </div>
    </div>
  );

  return (
    <div className={`human-input-card${answeredResponse ? " answered" : ""}`}>
      <div className="human-input-head">
        <div className="human-input-kicker">
          <span className="human-input-dot" aria-hidden />
          {request.title || "需要你的补充信息"}
        </div>
        {status && <span className="human-input-status">{status}</span>}
      </div>
      {request.context ? (
        <div className="human-input-context">{request.context}</div>
      ) : null}
      <div className="human-input-question">{request.question}</div>

      {showOptions && (
        <div className="human-input-options">
          {options.map((option, idx) => {
            const selected = answeredResponse?.response_kind === "option"
              && answeredResponse.option_id === option.id;
            return (
              <button
                key={option.id}
                type="button"
                className={`human-input-option${selected ? " selected" : ""}`}
                disabled={isDisabled}
                onClick={() => handleOption(option)}
              >
                <span className="human-input-option-n">{idx + 1}.</span>
                {option.label}
              </button>
            );
          })}
        </div>
      )}

      {isForm && !answeredResponse && (
        <div className="human-input-form">
          {(request.fields ?? []).map((field) => (
            <label key={field.name} className="human-input-field">
              <span className="human-input-field-label">
                {field.label}
                {field.required ? " *" : ""}
              </span>
              {field.type === "textarea" ? (
                <textarea
                  disabled={isDisabled}
                  placeholder={field.placeholder}
                  rows={3}
                  value={typeof formValues[field.name] === "string" ? String(formValues[field.name]) : ""}
                  onChange={(e) => setField(field.name, e.target.value)}
                />
              ) : field.type === "checkbox" ? (
                <input
                  type="checkbox"
                  disabled={isDisabled}
                  checked={formValues[field.name] === true}
                  onChange={(e) => setField(field.name, e.target.checked)}
                />
              ) : field.type === "select" ? (
                <select
                  disabled={isDisabled}
                  value={typeof formValues[field.name] === "string" ? String(formValues[field.name]) : ""}
                  onChange={(e) => setField(field.name, e.target.value)}
                >
                  <option value="">请选择</option>
                  {(field.options ?? []).map((opt) => (
                    <option key={opt.id} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
                  disabled={isDisabled}
                  placeholder={field.placeholder}
                  value={typeof formValues[field.name] === "string" ? String(formValues[field.name]) : ""}
                  onChange={(e) => setField(field.name, e.target.value)}
                />
              )}
            </label>
          ))}
          <div className="human-input-actions">
            {error ? <span className="human-input-error">{error}</span> : <span />}
            <button
              type="button"
              className="human-input-submit"
              disabled={isDisabled}
              onClick={handleFormSubmit}
            >
              {pending ? "提交中…" : "提交"}
            </button>
          </div>
        </div>
      )}

      {allowText && !answeredResponse && interactive && (
        otherCollapsed ? (
          <details className="human-input-other">
            <summary>或输入其它回答…</summary>
            {textEditor}
          </details>
        ) : textEditor
      )}

      {answeredResponse && (
        <div className="human-input-answered">
          已回答：{answeredResponse.value}
        </div>
      )}

      {interactive && (
        <div className="human-input-hint">也可在下方主输入框直接回复</div>
      )}
    </div>
  );
}
