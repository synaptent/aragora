/**
 * Aragora Diagnostics Provider
 *
 * Provides inline diagnostics (squiggles) for security issues and code quality findings.
 * Integrates with the Aragora API to analyze files on save.
 */

import * as vscode from 'vscode';
import type { SecurityFinding, Severity, CodeLocation } from '../types/messages';
import { getLogger } from '../logger';

const logger = getLogger();

interface AnalyzeResponse {
  findings: Array<{
    id: string;
    title: string;
    description: string;
    severity: string;
    category: string;
    line: number;
    column: number;
    end_line?: number;
    end_column?: number;
    suggestion?: string;
    cwe_id?: string;
    owasp_category?: string;
  }>;
}

/**
 * Maps Aragora severity to VSCode DiagnosticSeverity
 */
function mapSeverity(severity: Severity): vscode.DiagnosticSeverity {
  switch (severity) {
    case 'critical':
    case 'high':
      return vscode.DiagnosticSeverity.Error;
    case 'medium':
      return vscode.DiagnosticSeverity.Warning;
    case 'low':
      return vscode.DiagnosticSeverity.Information;
    case 'info':
    default:
      return vscode.DiagnosticSeverity.Hint;
  }
}

/**
 * Returns severity icon for display
 */
function getSeverityIcon(severity: Severity): string {
  switch (severity) {
    case 'critical':
      return '🔴';
    case 'high':
      return '🟠';
    case 'medium':
      return '🟡';
    case 'low':
      return '🔵';
    case 'info':
    default:
      return 'ℹ️';
  }
}

export class AragoraDiagnosticsProvider implements vscode.Disposable {
  private diagnosticCollection: vscode.DiagnosticCollection;
  private disposables: vscode.Disposable[] = [];
  private apiUrl!: string;
  private apiKey!: string;
  private analyzeOnSave!: boolean;
  private analyzeOnOpen!: boolean;
  private debounceTimers: Map<string, NodeJS.Timeout> = new Map();
  private findings: Map<string, SecurityFinding[]> = new Map();

  constructor() {
    this.diagnosticCollection = vscode.languages.createDiagnosticCollection('aragora');
    this.loadConfiguration();

    // Watch for configuration changes
    this.disposables.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('aragora')) {
          this.loadConfiguration();
        }
      }),
    );

    // Analyze on save
    this.disposables.push(
      vscode.workspace.onDidSaveTextDocument((document) => {
        if (this.analyzeOnSave && this.isAnalyzableDocument(document)) {
          this.analyzeDocument(document);
        }
      }),
    );

    // Analyze on open
    this.disposables.push(
      vscode.workspace.onDidOpenTextDocument((document) => {
        if (this.analyzeOnOpen && this.isAnalyzableDocument(document)) {
          this.analyzeDocument(document);
        }
      }),
    );

    // Clear diagnostics when document closes
    this.disposables.push(
      vscode.workspace.onDidCloseTextDocument((document) => {
        this.diagnosticCollection.delete(document.uri);
        this.findings.delete(document.uri.toString());
      }),
    );

    // Clear diagnostics when document content changes (debounced analysis)
    this.disposables.push(
      vscode.workspace.onDidChangeTextDocument((event) => {
        if (this.isAnalyzableDocument(event.document)) {
          this.scheduleAnalysis(event.document);
        }
      }),
    );
  }

  private loadConfiguration(): void {
    const config = vscode.workspace.getConfiguration('aragora');
    this.apiUrl = config.get('apiUrl') || 'https://api.aragora.ai';
    this.apiKey = config.get('apiKey') || '';
    this.analyzeOnSave = config.get('analyzeOnSave', true);
    this.analyzeOnOpen = config.get('analyzeOnOpen', false);
  }

  private isAnalyzableDocument(document: vscode.TextDocument): boolean {
    // Only analyze code files
    const analyzableLanguages = [
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
    return analyzableLanguages.includes(document.languageId) && document.uri.scheme === 'file';
  }

  private scheduleAnalysis(document: vscode.TextDocument): void {
    const key = document.uri.toString();
    const existing = this.debounceTimers.get(key);
    if (existing) {
      clearTimeout(existing);
    }

    // Debounce analysis to avoid too many API calls during typing
    const timer = setTimeout(() => {
      this.debounceTimers.delete(key);
      // Only run on-change analysis if explicitly enabled
      const config = vscode.workspace.getConfiguration('aragora');
      if (config.get('analyzeOnChange', false)) {
        this.analyzeDocument(document);
      }
    }, 2000);

    this.debounceTimers.set(key, timer);
  }

  /**
   * Analyze a document and update diagnostics
   */
  async analyzeDocument(document: vscode.TextDocument): Promise<SecurityFinding[]> {
    const uri = document.uri;
    const content = document.getText();
    const languageId = document.languageId;

    try {
      const findings = await this.callAnalyzeAPI(content, languageId, document.fileName);
      this.findings.set(uri.toString(), findings);
      this.updateDiagnostics(uri, findings);
      return findings;
    } catch (error) {
      logger.error('Aragora analysis failed:', error);
      // Don't clear existing diagnostics on error
      return this.findings.get(uri.toString()) || [];
    }
  }

  private async callAnalyzeAPI(
    content: string,
    language: string,
    fileName: string,
  ): Promise<SecurityFinding[]> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };

    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
    }

    try {
      const response = await fetch(`${this.apiUrl}/api/v1/codebase/analyze`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          content,
          language,
          file_name: fileName,
          analysis_types: ['security', 'quality', 'performance'],
        }),
      });

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      const data = (await response.json()) as AnalyzeResponse;
      return this.transformFindings(data.findings || []);
    } catch (error) {
      // Return mock findings for development/demo
      if (this.apiUrl.includes('localhost') || !this.apiKey) {
        return this.getMockFindings(content, language);
      }
      throw error;
    }
  }

  private transformFindings(apiFindings: AnalyzeResponse['findings']): SecurityFinding[] {
    return apiFindings.map((f) => ({
      id: f.id,
      title: f.title,
      description: f.description,
      severity: f.severity as Severity,
      category: f.category,
      location: {
        file: '',
        line: f.line,
        column: f.column,
        endLine: f.end_line,
        endColumn: f.end_column,
      },
      suggestion: f.suggestion,
      cweId: f.cwe_id,
      owaspCategory: f.owasp_category,
    }));
  }

  /**
   * Generate mock findings for development/demo purposes
   */
  private getMockFindings(content: string, language: string): SecurityFinding[] {
    const findings: SecurityFinding[] = [];
    const lines = content.split('\n');

    lines.forEach((line, index) => {
      // Check for hardcoded secrets
      if (/(?:password|secret|api_key|apikey|token)\s*[=:]\s*['"][^'"]+['"]/i.test(line)) {
        findings.push({
          id: `secret-${index}`,
          title: 'Hardcoded Secret Detected',
          description:
            'Sensitive data should not be hardcoded. Use environment variables or a secrets manager.',
          severity: 'critical',
          category: 'security',
          location: { file: '', line: index + 1, column: 0 },
          suggestion: 'Move this value to an environment variable',
          cweId: 'CWE-798',
          owaspCategory: 'A3:2017-Sensitive Data Exposure',
        });
      }

      // Check for SQL injection patterns (simplified)
      if (
        /(?:execute|query|raw)\s*\([^)]*\+|f['"].*{.*}.*(?:SELECT|INSERT|UPDATE|DELETE)/i.test(line)
      ) {
        findings.push({
          id: `sqli-${index}`,
          title: 'Potential SQL Injection',
          description: 'Dynamic SQL construction may be vulnerable to SQL injection attacks.',
          severity: 'high',
          category: 'security',
          location: { file: '', line: index + 1, column: 0 },
          suggestion: 'Use parameterized queries instead of string concatenation',
          cweId: 'CWE-89',
          owaspCategory: 'A1:2017-Injection',
        });
      }

      // Check for eval usage
      if (/\beval\s*\(/.test(line)) {
        findings.push({
          id: `eval-${index}`,
          title: 'Dangerous eval() Usage',
          description: 'Using eval() can lead to code injection vulnerabilities.',
          severity: 'high',
          category: 'security',
          location: { file: '', line: index + 1, column: line.indexOf('eval') },
          suggestion:
            'Avoid eval() - use safer alternatives like JSON.parse() or Function constructor',
          cweId: 'CWE-95',
        });
      }

      // Check for console.log in production code
      if (/console\.(log|debug|info)\s*\(/.test(line) && language.includes('script')) {
        findings.push({
          id: `console-${index}`,
          title: 'Console Statement in Code',
          description: 'Console statements should be removed from production code.',
          severity: 'low',
          category: 'quality',
          location: { file: '', line: index + 1, column: line.indexOf('console') },
          suggestion: 'Remove or replace with proper logging',
        });
      }

      // Check for TODO/FIXME comments
      if (/\b(TODO|FIXME|HACK|XXX)\b/i.test(line)) {
        const match = line.match(/\b(TODO|FIXME|HACK|XXX)\b/i);
        if (match) {
          findings.push({
            id: `todo-${index}`,
            title: `${match[1].toUpperCase()} Comment Found`,
            description: `Found a ${match[1].toUpperCase()} comment that may need attention.`,
            severity: 'info',
            category: 'quality',
            location: { file: '', line: index + 1, column: match.index || 0 },
          });
        }
      }
    });

    return findings;
  }

  private updateDiagnostics(uri: vscode.Uri, findings: SecurityFinding[]): void {
    const diagnostics: vscode.Diagnostic[] = findings.map((finding) => {
      const range = new vscode.Range(
        finding.location.line - 1,
        finding.location.column,
        finding.location.endLine ? finding.location.endLine - 1 : finding.location.line - 1,
        finding.location.endColumn || Number.MAX_VALUE,
      );

      const diagnostic = new vscode.Diagnostic(
        range,
        `${getSeverityIcon(finding.severity)} ${finding.title}: ${finding.description}`,
        mapSeverity(finding.severity),
      );

      diagnostic.source = 'Aragora';
      diagnostic.code = finding.cweId || finding.category;

      // Add related information if available
      if (finding.suggestion) {
        diagnostic.relatedInformation = [
          new vscode.DiagnosticRelatedInformation(
            new vscode.Location(uri, range),
            `💡 Suggestion: ${finding.suggestion}`,
          ),
        ];
      }

      // Tag for filtering
      if (finding.severity === 'critical' || finding.severity === 'high') {
        diagnostic.tags = [];
      }

      return diagnostic;
    });

    this.diagnosticCollection.set(uri, diagnostics);
  }

  /**
   * Get findings for a specific file
   */
  getFindings(uri: vscode.Uri): SecurityFinding[] {
    return this.findings.get(uri.toString()) || [];
  }

  /**
   * Get all findings across all files
   */
  getAllFindings(): Map<string, SecurityFinding[]> {
    return new Map(this.findings);
  }

  /**
   * Clear diagnostics for a specific file
   */
  clearDiagnostics(uri: vscode.Uri): void {
    this.diagnosticCollection.delete(uri);
    this.findings.delete(uri.toString());
  }

  /**
   * Clear all diagnostics
   */
  clearAllDiagnostics(): void {
    this.diagnosticCollection.clear();
    this.findings.clear();
  }

  /**
   * Analyze all open documents
   */
  async analyzeAllOpenDocuments(): Promise<void> {
    const documents = vscode.workspace.textDocuments.filter((doc) =>
      this.isAnalyzableDocument(doc),
    );

    await Promise.all(documents.map((doc) => this.analyzeDocument(doc)));
  }

  /**
   * Analyze entire workspace
   */
  async analyzeWorkspace(
    progress?: vscode.Progress<{ message?: string; increment?: number }>,
  ): Promise<Map<string, SecurityFinding[]>> {
    const results = new Map<string, SecurityFinding[]>();

    // Find all code files in workspace
    const files = await vscode.workspace.findFiles(
      '**/*.{js,ts,jsx,tsx,py,java,go,rs,c,cpp,cs,php,rb,swift,kt}',
      '**/node_modules/**',
    );

    const total = files.length;
    let processed = 0;

    for (const file of files) {
      try {
        const document = await vscode.workspace.openTextDocument(file);
        const findings = await this.analyzeDocument(document);
        if (findings.length > 0) {
          results.set(file.fsPath, findings);
        }
      } catch (error) {
        logger.error(`Failed to analyze ${file.fsPath}:`, error);
      }

      processed++;
      if (progress) {
        progress.report({
          message: `Analyzing ${file.fsPath.split('/').pop()}`,
          increment: (1 / total) * 100,
        });
      }
    }

    return results;
  }

  dispose(): void {
    this.diagnosticCollection.dispose();
    this.debounceTimers.forEach((timer) => clearTimeout(timer));
    this.debounceTimers.clear();
    this.disposables.forEach((d) => d.dispose());
  }
}
