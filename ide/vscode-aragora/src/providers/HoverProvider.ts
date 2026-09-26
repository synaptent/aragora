/**
 * Aragora Hover Provider
 *
 * Provides rich hover information for security findings and code analysis.
 * Shows detailed information when hovering over code with detected issues.
 */

import * as vscode from 'vscode';
import type { AragoraDiagnosticsProvider } from './DiagnosticsProvider';
import type { SecurityFinding, Severity } from '../types/messages';

/**
 * Returns severity icon for display
 */
function getSeverityIcon(severity: Severity): string {
  switch (severity) {
    case 'critical':
      return '$(error)';
    case 'high':
      return '$(warning)';
    case 'medium':
      return '$(info)';
    case 'low':
      return '$(lightbulb)';
    case 'info':
    default:
      return '$(comment)';
  }
}

/**
 * Returns severity color class
 */
function getSeverityColor(severity: Severity): string {
  switch (severity) {
    case 'critical':
      return '#f44336';
    case 'high':
      return '#ff9800';
    case 'medium':
      return '#ffeb3b';
    case 'low':
      return '#2196f3';
    case 'info':
    default:
      return '#9e9e9e';
  }
}

class AragoraHoverProvider implements vscode.HoverProvider {
  private diagnosticsProvider: AragoraDiagnosticsProvider;

  constructor(diagnosticsProvider: AragoraDiagnosticsProvider) {
    this.diagnosticsProvider = diagnosticsProvider;
  }

  provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    _token: vscode.CancellationToken
  ): vscode.ProviderResult<vscode.Hover> {
    const findings = this.diagnosticsProvider.getFindings(document.uri);
    if (findings.length === 0) {
      return null;
    }

    // Find findings at the current position
    const relevantFindings = findings.filter((finding) => {
      const startLine = finding.location.line - 1;
      const endLine = finding.location.endLine
        ? finding.location.endLine - 1
        : startLine;

      return position.line >= startLine && position.line <= endLine;
    });

    if (relevantFindings.length === 0) {
      return null;
    }

    const contents = this.buildHoverContent(relevantFindings);
    return new vscode.Hover(contents);
  }

  private buildHoverContent(findings: SecurityFinding[]): vscode.MarkdownString[] {
    return findings.map((finding) => {
      const md = new vscode.MarkdownString();
      md.isTrusted = true;
      md.supportHtml = true;

      // Header with severity badge
      const icon = getSeverityIcon(finding.severity);
      const color = getSeverityColor(finding.severity);
      md.appendMarkdown(
        `### ${icon} ${finding.title}\n\n`
      );

      // Severity badge
      md.appendMarkdown(
        `<span style="background-color:${color};color:white;padding:2px 6px;border-radius:3px;font-size:10px;text-transform:uppercase;">${finding.severity}</span>`
      );

      if (finding.category) {
        md.appendMarkdown(
          ` <span style="background-color:#555;color:white;padding:2px 6px;border-radius:3px;font-size:10px;">${finding.category}</span>`
        );
      }

      md.appendMarkdown('\n\n');

      // Description
      md.appendMarkdown(`${finding.description}\n\n`);

      // CWE/OWASP references
      if (finding.cweId || finding.owaspCategory) {
        md.appendMarkdown('**References:**\n');
        if (finding.cweId) {
          md.appendMarkdown(
            `- [${finding.cweId}](https://cwe.mitre.org/data/definitions/${finding.cweId.replace('CWE-', '')}.html)\n`
          );
        }
        if (finding.owaspCategory) {
          md.appendMarkdown(`- ${finding.owaspCategory}\n`);
        }
        md.appendMarkdown('\n');
      }

      // Suggestion
      if (finding.suggestion) {
        md.appendMarkdown('---\n\n');
        md.appendMarkdown(`**$(lightbulb) Suggestion:** ${finding.suggestion}\n\n`);
      }

      // Quick actions
      md.appendMarkdown('---\n\n');
      const fixCommand = `command:aragora.fixIssue?${encodeURIComponent(JSON.stringify({ findingId: finding.id }))}`;
      const explainCommand = `command:aragora.explainCode`;

      md.appendMarkdown(
        `[$(wrench) Fix Issue](${fixCommand}) | [$(question) Explain](${explainCommand})`
      );

      return md;
    });
  }
}

/**
 * Register the hover provider for supported languages
 */
export function registerHoverProvider(
  context: vscode.ExtensionContext,
  diagnosticsProvider: AragoraDiagnosticsProvider
): vscode.Disposable {
  const hoverProvider = new AragoraHoverProvider(diagnosticsProvider);

  const languages = [
    'javascript',
    'typescript',
    'javascriptreact',
    'typescriptreact',
    'python',
    'java',
    'go',
    'rust',
    'c',
    'cpp',
    'csharp',
    'php',
    'ruby',
    'swift',
    'kotlin',
  ];

  const disposables = languages.map((language) =>
    vscode.languages.registerHoverProvider(
      { language, scheme: 'file' },
      hoverProvider
    )
  );

  const disposable = vscode.Disposable.from(...disposables);
  context.subscriptions.push(disposable);

  return disposable;
}
