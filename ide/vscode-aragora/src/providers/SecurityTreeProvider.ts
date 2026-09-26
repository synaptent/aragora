/**
 * Aragora Security Tree Provider
 *
 * Provides a tree view of security findings grouped by severity.
 * Enables navigation to findings and bulk actions.
 */

import * as vscode from 'vscode';
import type { SecurityFinding, Severity } from '../types/messages';
import { SEVERITY_PRIORITY, compareSeverity } from '../types/messages';

/**
 * Tree item representing a severity group or individual finding
 */
class SecurityTreeItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly finding?: SecurityFinding,
    public readonly severity?: Severity,
    public readonly count?: number,
  ) {
    super(label, collapsibleState);

    if (finding) {
      // This is a finding item
      this.setupFindingItem(finding);
    } else if (severity && count !== undefined) {
      // This is a severity group
      this.setupSeverityGroup(severity, count);
    }
  }

  private setupFindingItem(finding: SecurityFinding): void {
    this.tooltip = new vscode.MarkdownString(
      `**${finding.title}**\n\n${finding.description}\n\n` +
        `📁 ${finding.location.file.split('/').pop()}:${finding.location.line}\n\n` +
        (finding.cweId ? `🔗 ${finding.cweId}\n` : '') +
        (finding.suggestion ? `\n💡 **Suggestion:** ${finding.suggestion}` : ''),
    );

    this.description = `${finding.location.file.split('/').pop()}:${finding.location.line}`;

    // Command to navigate to the finding
    this.command = {
      command: 'aragora.navigateToFinding',
      title: 'Go to Finding',
      arguments: [finding],
    };

    // Context value for context menu
    this.contextValue = 'finding';

    // Icon based on category
    this.iconPath = this.getCategoryIcon(finding.category);
  }

  private setupSeverityGroup(severity: Severity, count: number): void {
    this.description = `${count} issue${count !== 1 ? 's' : ''}`;
    this.tooltip = `${count} ${severity} severity issue${count !== 1 ? 's' : ''}`;
    this.contextValue = 'severityGroup';
    this.iconPath = this.getSeverityIcon(severity);
  }

  private getSeverityIcon(severity: Severity): vscode.ThemeIcon {
    const iconMap: Record<Severity, { icon: string; color?: string }> = {
      critical: { icon: 'error', color: 'errorForeground' },
      high: { icon: 'warning', color: 'problemsWarningIcon.foreground' },
      medium: { icon: 'info', color: 'problemsInfoIcon.foreground' },
      low: { icon: 'circle-outline', color: 'foreground' },
      info: { icon: 'lightbulb', color: 'foreground' },
    };

    const config = iconMap[severity];
    return new vscode.ThemeIcon(
      config.icon,
      config.color ? new vscode.ThemeColor(config.color) : undefined,
    );
  }

  private getCategoryIcon(category: string): vscode.ThemeIcon {
    const iconMap: Record<string, string> = {
      security: 'shield',
      quality: 'checklist',
      performance: 'dashboard',
      accessibility: 'accessibility',
      maintainability: 'tools',
      bug: 'bug',
      default: 'circle-outline',
    };

    return new vscode.ThemeIcon(iconMap[category] || iconMap.default);
  }
}

export class SecurityTreeProvider implements vscode.TreeDataProvider<SecurityTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<SecurityTreeItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private findings: Map<string, SecurityFinding[]> = new Map();
  private groupedFindings: Map<Severity, SecurityFinding[]> = new Map();
  private disposables: vscode.Disposable[] = [];

  constructor(private diagnosticsProvider?: { getAllFindings(): Map<string, SecurityFinding[]> }) {
    // Refresh when diagnostics change
    if (diagnosticsProvider) {
      this.refresh();
    }
  }

  /**
   * Refresh the tree view with latest findings
   */
  refresh(): void {
    if (this.diagnosticsProvider) {
      this.findings = this.diagnosticsProvider.getAllFindings();
    }
    this.groupFindingsBySeverity();
    this._onDidChangeTreeData.fire(undefined);
  }

  /**
   * Set findings directly (e.g., from workspace scan)
   */
  setFindings(findings: Map<string, SecurityFinding[]>): void {
    this.findings = findings;
    this.groupFindingsBySeverity();
    this._onDidChangeTreeData.fire(undefined);
  }

  /**
   * Add findings for a specific file
   */
  addFindings(file: string, findings: SecurityFinding[]): void {
    this.findings.set(file, findings);
    this.groupFindingsBySeverity();
    this._onDidChangeTreeData.fire(undefined);
  }

  /**
   * Clear all findings
   */
  clear(): void {
    this.findings.clear();
    this.groupedFindings.clear();
    this._onDidChangeTreeData.fire(undefined);
  }

  private groupFindingsBySeverity(): void {
    this.groupedFindings.clear();

    for (const [file, fileFindings] of this.findings) {
      for (const finding of fileFindings) {
        // Update finding with file path
        const enrichedFinding = { ...finding, location: { ...finding.location, file } };

        const severity = finding.severity;
        const existing = this.groupedFindings.get(severity) || [];
        existing.push(enrichedFinding);
        this.groupedFindings.set(severity, existing);
      }
    }

    // Sort findings within each group by file and line
    for (const [severity, findings] of this.groupedFindings) {
      findings.sort((a, b) => {
        const fileCompare = a.location.file.localeCompare(b.location.file);
        if (fileCompare !== 0) return fileCompare;
        return a.location.line - b.location.line;
      });
    }
  }

  getTreeItem(element: SecurityTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: SecurityTreeItem): SecurityTreeItem[] {
    if (!element) {
      // Root level - show severity groups
      return this.getSeverityGroups();
    }

    if (element.severity) {
      // Severity group - show findings
      const findings = this.groupedFindings.get(element.severity) || [];
      return findings.map(
        (f) => new SecurityTreeItem(f.title, vscode.TreeItemCollapsibleState.None, f),
      );
    }

    return [];
  }

  private getSeverityGroups(): SecurityTreeItem[] {
    const groups: SecurityTreeItem[] = [];

    // Sort severities by priority
    const severities: Severity[] = ['critical', 'high', 'medium', 'low', 'info'];

    for (const severity of severities) {
      const findings = this.groupedFindings.get(severity);
      if (findings && findings.length > 0) {
        groups.push(
          new SecurityTreeItem(
            this.formatSeverityLabel(severity),
            vscode.TreeItemCollapsibleState.Expanded,
            undefined,
            severity,
            findings.length,
          ),
        );
      }
    }

    return groups;
  }

  private formatSeverityLabel(severity: Severity): string {
    const labels: Record<Severity, string> = {
      critical: '🔴 Critical',
      high: '🟠 High',
      medium: '🟡 Medium',
      low: '🔵 Low',
      info: 'ℹ️ Info',
    };
    return labels[severity];
  }

  /**
   * Get total count of findings
   */
  getTotalCount(): number {
    let total = 0;
    for (const findings of this.groupedFindings.values()) {
      total += findings.length;
    }
    return total;
  }

  /**
   * Get count by severity
   */
  getCountBySeverity(): Record<Severity, number> {
    const counts: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };

    for (const [severity, findings] of this.groupedFindings) {
      counts[severity] = findings.length;
    }

    return counts;
  }

  /**
   * Get all findings for export
   */
  getAllFindings(): SecurityFinding[] {
    const all: SecurityFinding[] = [];
    for (const findings of this.groupedFindings.values()) {
      all.push(...findings);
    }
    return all.sort((a, b) => compareSeverity(a.severity, b.severity));
  }

  dispose(): void {
    this.disposables.forEach((d) => d.dispose());
  }
}

/**
 * Register security tree commands
 */
export function registerSecurityTreeCommands(
  context: vscode.ExtensionContext,
  treeProvider: SecurityTreeProvider,
): void {
  // Navigate to finding
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.navigateToFinding',
      async (finding: SecurityFinding) => {
        const uri = vscode.Uri.file(finding.location.file);
        const document = await vscode.workspace.openTextDocument(uri);
        const editor = await vscode.window.showTextDocument(document);

        const line = finding.location.line - 1;
        const column = finding.location.column;
        const endLine = finding.location.endLine ? finding.location.endLine - 1 : line;
        const endColumn = finding.location.endColumn || column + 10;

        const range = new vscode.Range(line, column, endLine, endColumn);
        editor.selection = new vscode.Selection(range.start, range.end);
        editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
      },
    ),
  );

  // Fix finding
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.fixFinding', async (item: SecurityTreeItem) => {
      if (!item.finding) return;

      const uri = vscode.Uri.file(item.finding.location.file);
      const diagnostic = new vscode.Diagnostic(
        new vscode.Range(
          item.finding.location.line - 1,
          item.finding.location.column,
          item.finding.location.line - 1,
          item.finding.location.column + 10,
        ),
        item.finding.description,
        vscode.DiagnosticSeverity.Warning,
      );

      await vscode.commands.executeCommand('aragora.fixIssue', uri, diagnostic);
      treeProvider.refresh();
    }),
  );

  // Ignore finding
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.ignoreFinding', async (item: SecurityTreeItem) => {
      if (!item.finding) return;

      const scope = await vscode.window.showQuickPick(
        [
          { label: 'This file', value: 'file' },
          { label: 'Entire workspace', value: 'workspace' },
          { label: 'Globally', value: 'global' },
        ],
        { placeHolder: 'Ignore this finding in...' },
      );

      if (!scope) return;

      // Store ignored findings (this would integrate with configuration)
      const config = vscode.workspace.getConfiguration('aragora');
      const ignored = config.get<string[]>('ignoredFindings', []);
      ignored.push(item.finding.id);
      await config.update('ignoredFindings', ignored, scope.value === 'global');

      vscode.window.showInformationMessage(`Finding ignored for ${scope.label.toLowerCase()}`);
      treeProvider.refresh();
    }),
  );

  // Fix all in severity group
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.fixAllInGroup', async (item: SecurityTreeItem) => {
      if (!item.severity) return;

      const findings = treeProvider.getAllFindings().filter((f) => f.severity === item.severity);

      const choice = await vscode.window.showWarningMessage(
        `Fix all ${findings.length} ${item.severity} severity issues?`,
        'Yes, Fix All',
        'Cancel',
      );

      if (choice !== 'Yes, Fix All') return;

      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: `Fixing ${item.severity} issues`,
          cancellable: false,
        },
        async (progress) => {
          let fixed = 0;
          for (const finding of findings) {
            try {
              const uri = vscode.Uri.file(finding.location.file);
              const diagnostic = new vscode.Diagnostic(
                new vscode.Range(
                  finding.location.line - 1,
                  finding.location.column,
                  finding.location.line - 1,
                  finding.location.column + 10,
                ),
                finding.description,
                vscode.DiagnosticSeverity.Warning,
              );
              await vscode.commands.executeCommand('aragora.fixIssue', uri, diagnostic);
              fixed++;
              progress.report({
                message: `Fixed ${fixed}/${findings.length}`,
                increment: (1 / findings.length) * 100,
              });
            } catch (error) {
              console.error(`Failed to fix finding: ${error}`);
            }
          }
          vscode.window.showInformationMessage(`Fixed ${fixed}/${findings.length} issues`);
        },
      );

      treeProvider.refresh();
    }),
  );

  // Export findings
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.exportFindings', async () => {
      const findings = treeProvider.getAllFindings();

      if (findings.length === 0) {
        vscode.window.showInformationMessage('No findings to export');
        return;
      }

      const format = await vscode.window.showQuickPick(
        [
          { label: 'JSON', value: 'json' },
          { label: 'Markdown', value: 'markdown' },
          { label: 'CSV', value: 'csv' },
        ],
        { placeHolder: 'Export format' },
      );

      if (!format) return;

      let content: string;
      let language: string;

      switch (format.value) {
        case 'json':
          content = JSON.stringify(findings, null, 2);
          language = 'json';
          break;

        case 'markdown':
          content = generateMarkdownReport(findings);
          language = 'markdown';
          break;

        case 'csv':
          content = generateCSVReport(findings);
          language = 'plaintext';
          break;

        default:
          return;
      }

      const doc = await vscode.workspace.openTextDocument({ content, language });
      await vscode.window.showTextDocument(doc);
    }),
  );

  // Refresh tree
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.refreshSecurityTree', () => {
      treeProvider.refresh();
    }),
  );
}

function generateMarkdownReport(findings: SecurityFinding[]): string {
  const lines = [
    '# Security Findings Report',
    '',
    `Generated: ${new Date().toISOString()}`,
    '',
    `Total Issues: ${findings.length}`,
    '',
    '## Summary',
    '',
    '| Severity | Count |',
    '|----------|-------|',
  ];

  const counts: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
  for (const finding of findings) {
    counts[finding.severity]++;
  }

  for (const [severity, count] of Object.entries(counts)) {
    if (count > 0) {
      lines.push(`| ${severity} | ${count} |`);
    }
  }

  lines.push('', '## Findings', '');

  for (const finding of findings) {
    lines.push(
      `### ${finding.severity.toUpperCase()}: ${finding.title}`,
      '',
      `**File:** ${finding.location.file}:${finding.location.line}`,
      '',
      finding.description,
      '',
    );

    if (finding.cweId) {
      lines.push(`**CWE:** ${finding.cweId}`, '');
    }

    if (finding.suggestion) {
      lines.push(`**Suggestion:** ${finding.suggestion}`, '');
    }

    lines.push('---', '');
  }

  return lines.join('\n');
}

function generateCSVReport(findings: SecurityFinding[]): string {
  const headers = ['Severity', 'Title', 'Description', 'File', 'Line', 'CWE', 'Suggestion'];
  const rows = [headers.join(',')];

  for (const finding of findings) {
    const row = [
      finding.severity,
      `"${finding.title.replace(/"/g, '""')}"`,
      `"${finding.description.replace(/"/g, '""')}"`,
      finding.location.file,
      finding.location.line.toString(),
      finding.cweId || '',
      finding.suggestion ? `"${finding.suggestion.replace(/"/g, '""')}"` : '',
    ];
    rows.push(row.join(','));
  }

  return rows.join('\n');
}
