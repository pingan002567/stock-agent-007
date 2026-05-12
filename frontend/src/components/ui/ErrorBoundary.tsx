import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.props.onError?.(error, info);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", padding: "40px 20px", gap: 12,
          textAlign: "center", minHeight: 200,
        }}>
          <div style={{ fontSize: 32, lineHeight: 1, opacity: 0.4 }}>!</div>
          <div style={{ fontWeight: 600, fontSize: 14 }}>页面渲染异常</div>
          <div className="muted" style={{ fontSize: 12, maxWidth: 400, lineHeight: 1.5, wordBreak: "break-word" }}>
            {this.state.error?.message || "未知错误"}
          </div>
          <button
            className="primary"
            onClick={this.handleRetry}
            type="button"
            style={{ marginTop: 8, height: 32, fontSize: 12, padding: "0 16px" }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
