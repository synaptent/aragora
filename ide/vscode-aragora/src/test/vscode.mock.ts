/**
 * Mock VSCode module for unit testing.
 *
 * This provides minimal mock implementations of VSCode APIs
 * needed for testing provider logic.
 */

// Mock URI
export class MockUri {
  constructor(
    public readonly scheme: string,
    public readonly path: string,
    public readonly fsPath: string = path,
  ) {}

  static file(path: string): MockUri {
    return new MockUri('file', path, path);
  }

  static parse(uri: string): MockUri {
    const match = uri.match(/^(\w+):\/\/(.*)$/);
    if (match) {
      return new MockUri(match[1], match[2]);
    }
    return new MockUri('file', uri);
  }

  toString(): string {
    return `${this.scheme}://${this.path}`;
  }
}

// Mock Position
export class MockPosition {
  constructor(
    public readonly line: number,
    public readonly character: number,
  ) {}

  isEqual(other: MockPosition): boolean {
    return this.line === other.line && this.character === other.character;
  }

  isBefore(other: MockPosition): boolean {
    return this.line < other.line || (this.line === other.line && this.character < other.character);
  }

  isAfter(other: MockPosition): boolean {
    return this.line > other.line || (this.line === other.line && this.character > other.character);
  }
}

// Mock Range
export class MockRange {
  constructor(
    public readonly start: MockPosition,
    public readonly end: MockPosition,
  ) {}

  static fromNumbers(
    startLine: number,
    startChar: number,
    endLine: number,
    endChar: number,
  ): MockRange {
    return new MockRange(
      new MockPosition(startLine, startChar),
      new MockPosition(endLine, endChar),
    );
  }

  get isEmpty(): boolean {
    return this.start.isEqual(this.end);
  }

  contains(position: MockPosition): boolean {
    return !position.isBefore(this.start) && !position.isAfter(this.end);
  }
}

// Mock Selection
export class MockSelection extends MockRange {
  constructor(
    public readonly anchor: MockPosition,
    public readonly active: MockPosition,
  ) {
    super(anchor, active);
  }

  get isReversed(): boolean {
    return this.anchor.isAfter(this.active);
  }
}

// Mock Diagnostic Severity
export enum MockDiagnosticSeverity {
  Error = 0,
  Warning = 1,
  Information = 2,
  Hint = 3,
}

// Mock Diagnostic
export class MockDiagnostic {
  constructor(
    public range: MockRange,
    public message: string,
    public severity: MockDiagnosticSeverity = MockDiagnosticSeverity.Warning,
  ) {}

  source?: string;
  code?: string | number;
  relatedInformation?: Array<{ message: string }>;
}

// Mock Code Action Kind
export class MockCodeActionKind {
  static readonly Empty = new MockCodeActionKind('');
  static readonly QuickFix = new MockCodeActionKind('quickfix');
  static readonly Refactor = new MockCodeActionKind('refactor');
  static readonly RefactorExtract = new MockCodeActionKind('refactor.extract');
  static readonly RefactorInline = new MockCodeActionKind('refactor.inline');
  static readonly RefactorRewrite = new MockCodeActionKind('refactor.rewrite');
  static readonly Source = new MockCodeActionKind('source');
  static readonly SourceOrganizeImports = new MockCodeActionKind('source.organizeImports');
  static readonly SourceFixAll = new MockCodeActionKind('source.fixAll');

  constructor(public readonly value: string) {}

  contains(other: MockCodeActionKind): boolean {
    return other.value.startsWith(this.value);
  }
}

// Mock Code Action
export class MockCodeAction {
  command?: { command: string; title: string; arguments?: unknown[]; tooltip?: string };
  diagnostics?: MockDiagnostic[];
  isPreferred?: boolean;
  edit?: unknown;

  constructor(
    public title: string,
    public kind?: MockCodeActionKind,
  ) {}
}

// Mock Tree Item
export class MockTreeItem {
  tooltip?: string | MockMarkdownString;
  description?: string;
  command?: { command: string; title: string; arguments?: unknown[] };
  contextValue?: string;
  iconPath?: MockThemeIcon;

  constructor(
    public label: string,
    public collapsibleState: MockTreeItemCollapsibleState = MockTreeItemCollapsibleState.None,
  ) {}
}

// Mock Tree Item Collapsible State
export enum MockTreeItemCollapsibleState {
  None = 0,
  Collapsed = 1,
  Expanded = 2,
}

// Mock Theme Icon
export class MockThemeIcon {
  constructor(
    public readonly id: string,
    public readonly color?: MockThemeColor,
  ) {}
}

// Mock Theme Color
export class MockThemeColor {
  constructor(public readonly id: string) {}
}

// Mock Markdown String
export class MockMarkdownString {
  isTrusted = false;
  supportHtml = false;
  private value = '';

  constructor(value?: string) {
    this.value = value || '';
  }

  appendMarkdown(value: string): MockMarkdownString {
    this.value += value;
    return this;
  }

  appendText(value: string): MockMarkdownString {
    this.value += value;
    return this;
  }

  toString(): string {
    return this.value;
  }
}

// Mock Hover
export class MockHover {
  constructor(
    public contents: MockMarkdownString | MockMarkdownString[],
    public range?: MockRange,
  ) {}
}

// Mock EventEmitter
export class MockEventEmitter<T> {
  private listeners: Array<(e: T) => void> = [];

  event = (listener: (e: T) => void): { dispose(): void } => {
    this.listeners.push(listener);
    return {
      dispose: () => {
        const index = this.listeners.indexOf(listener);
        if (index !== -1) {
          this.listeners.splice(index, 1);
        }
      },
    };
  };

  fire(event: T): void {
    for (const listener of this.listeners) {
      listener(event);
    }
  }

  dispose(): void {
    this.listeners = [];
  }
}

// Mock Disposable
export class MockDisposable {
  private disposed = false;

  constructor(private callback?: () => void) {}

  dispose(): void {
    if (!this.disposed) {
      this.disposed = true;
      if (this.callback) {
        this.callback();
      }
    }
  }

  static from(...disposables: { dispose(): void }[]): MockDisposable {
    return new MockDisposable(() => {
      for (const d of disposables) {
        d.dispose();
      }
    });
  }
}

// Mock TextLine
export class MockTextLine {
  constructor(
    public readonly lineNumber: number,
    public readonly text: string,
    public readonly range: MockRange,
    public readonly rangeIncludingLineBreak: MockRange,
    public readonly firstNonWhitespaceCharacterIndex: number = 0,
    public readonly isEmptyOrWhitespace: boolean = false,
  ) {}
}

// Mock TextDocument
export class MockTextDocument {
  private lines: string[];

  constructor(
    public readonly uri: MockUri,
    public readonly languageId: string,
    public readonly content: string,
    public readonly fileName: string = uri.fsPath,
  ) {
    this.lines = this.content.split('\n');
  }

  get lineCount(): number {
    return this.lines.length;
  }

  lineAt(line: number): MockTextLine {
    const text = this.lines[line] || '';
    return new MockTextLine(
      line,
      text,
      MockRange.fromNumbers(line, 0, line, text.length),
      MockRange.fromNumbers(line, 0, line, text.length + 1),
      text.search(/\S/),
      text.trim().length === 0,
    );
  }

  getText(range?: MockRange): string {
    if (!range) {
      return this.content;
    }
    const lines: string[] = [];
    for (let i = range.start.line; i <= range.end.line; i++) {
      let text = this.lines[i] || '';
      if (i === range.start.line) {
        text = text.substring(range.start.character);
      }
      if (i === range.end.line) {
        text = text.substring(
          0,
          range.end.character - (i === range.start.line ? range.start.character : 0),
        );
      }
      lines.push(text);
    }
    return lines.join('\n');
  }
}

// Export combined mock module
export const vscode = {
  Uri: MockUri,
  Position: MockPosition,
  Range: MockRange,
  Selection: MockSelection,
  DiagnosticSeverity: MockDiagnosticSeverity,
  Diagnostic: MockDiagnostic,
  CodeActionKind: MockCodeActionKind,
  CodeAction: MockCodeAction,
  TreeItem: MockTreeItem,
  TreeItemCollapsibleState: MockTreeItemCollapsibleState,
  ThemeIcon: MockThemeIcon,
  ThemeColor: MockThemeColor,
  MarkdownString: MockMarkdownString,
  Hover: MockHover,
  EventEmitter: MockEventEmitter,
  Disposable: MockDisposable,
};
