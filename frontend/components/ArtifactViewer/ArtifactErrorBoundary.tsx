import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; resetKey: string };
type State = { failed: boolean };

/**
 * Keeps an unrenderable artifact from taking the workspace down with it.
 *
 * The preview is the only part that touches model output, so it is the only
 * part that is guarded; the conversation stays usable either way.
 */
export class ArtifactErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidUpdate(previous: Props) {
    if (previous.resetKey !== this.props.resetKey && this.state.failed) {
      this.setState({ failed: false });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Component stack only; never surfaced in the UI.
    console.error("Artifact preview failed to render", error.message, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <div
          role="alert"
          className="flex h-full items-center justify-center p-6 text-center"
        >
          <div className="max-w-sm">
            <p className="text-sm font-medium text-foreground">
              This artifact could not be previewed.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              The conversation is unaffected. The raw source is still available
              under Code.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
