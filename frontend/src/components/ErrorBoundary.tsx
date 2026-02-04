/**
 * ErrorBoundary component to catch React errors and display user-friendly fallback UI.
 *
 * Features:
 * - Catches unhandled React errors
 * - Displays user-friendly error message
 * - Provides retry mechanism
 * - Logs errors to console in dev mode
 */

import { Component, ErrorInfo, ReactNode } from 'react';
import toast from 'react-hot-toast';
import './ErrorBoundary.css';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error to console in development mode
    if (import.meta.env.DEV) {
      console.error('Error Boundary caught an error:', error, errorInfo);
    }

    // Show toast notification
    toast.error('An unexpected error occurred. Please try again.');

    this.setState({
      errorInfo,
    });
  }

  handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-content">
            <h2>Oops! Something went wrong</h2>
            <p className="error-message">
              We encountered an unexpected error. Please try refreshing the page or contact support
              if the problem persists.
            </p>
            {import.meta.env.DEV && this.state.error && (
              <details className="error-details">
                <summary>Error Details (Development Mode)</summary>
                <pre className="error-stack">
                  {this.state.error.toString()}
                  {this.state.errorInfo?.componentStack}
                </pre>
              </details>
            )}
            <div className="error-actions">
              <button type="button" onClick={this.handleReset} className="retry-button">
                Try Again
              </button>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="reload-button"
              >
                Reload Page
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
