#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import ts from 'typescript';

const usage = `Usage: node scripts/check_dead_flags.mjs [--src-dir PATH] [--help]
  --src-dir PATH  Source root (default: this app's src/); declares lib/flags.ts.
  --help         Print this help.
Scans JS/TS source for imported flags.name or flags['name'] reads (aliases allowed).
Excludes lib/flags.ts, declarations, __tests__/, *.test.* and *.spec.*.
Exit codes: 0 all flags referenced (or help); 1 unreferenced flags; 2 input/parse error.
`;

function parseSource(path) {
  const source = ts.createSourceFile(
    path,
    readFileSync(path, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
  );
  if (source.parseDiagnostics.length) throw new Error(`Cannot parse ${path}`);
  return source;
}

function declaredFlags(source) {
  const statement = source.statements.find(
    (node) =>
      ts.isVariableStatement(node) &&
      node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword) &&
      node.declarationList.declarations.some((decl) => decl.name.getText(source) === 'flags'),
  );
  let object = statement?.declarationList.declarations.find(
    (decl) => decl.name.getText(source) === 'flags',
  )?.initializer;
  while (object && (ts.isAsExpression(object) || ts.isParenthesizedExpression(object))) {
    object = object.expression;
  }
  if (!object || !ts.isObjectLiteralExpression(object)) {
    throw new Error('Expected export const flags = { ... } as const in lib/flags.ts');
  }
  return object.properties.map((property) => {
    if (
      !ts.isPropertyAssignment(property) ||
      (!ts.isIdentifier(property.name) && !ts.isStringLiteral(property.name))
    ) {
      throw new Error('Flags must be explicit named properties, not spreads or computed keys');
    }
    return property.name.text;
  });
}

function importedNames(source, srcDir, declarationPath) {
  const names = new Set();
  for (const node of source.statements) {
    if (!ts.isImportDeclaration(node) || !ts.isStringLiteral(node.moduleSpecifier)) continue;
    const specifier = node.moduleSpecifier.text;
    const target = specifier.startsWith('@/')
      ? resolve(srcDir, specifier.slice(2))
      : resolve(dirname(source.fileName), specifier);
    if (target.replace(/\.[jt]sx?$/, '') !== declarationPath.replace(/\.ts$/, '')) continue;
    const bindings = node.importClause?.namedBindings;
    if (node.importClause?.isTypeOnly || !bindings || !ts.isNamedImports(bindings)) continue;
    for (const binding of bindings.elements) {
      if (!binding.isTypeOnly && (binding.propertyName || binding.name).text === 'flags') {
        names.add(binding.name.text);
      }
    }
  }
  return names;
}

function collectReferences(source, names, referenced) {
  function visit(node) {
    if (
      (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) &&
      ts.isIdentifier(node.expression) &&
      names.has(node.expression.text)
    ) {
      const key = ts.isPropertyAccessExpression(node) ? node.name : node.argumentExpression;
      if (ts.isIdentifier(key) && ts.isPropertyAccessExpression(node)) referenced.add(key.text);
      if (ts.isStringLiteral(key)) referenced.add(key.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}

function main() {
  const { values } = parseArgs({
    options: { help: { type: 'boolean' }, 'src-dir': { type: 'string' } },
  });
  if (values.help) {
    console.log(usage);
    return 0;
  }
  const srcDir = resolve(values['src-dir'] || fileURLToPath(new URL('../src/', import.meta.url)));
  const declarationPath = resolve(srcDir, 'lib/flags.ts');
  const declared = declaredFlags(parseSource(declarationPath));
  const referenced = new Set();
  const sources = ts.sys.readDirectory(
    srcDir,
    ['.ts', '.tsx', '.js', '.jsx'],
    ['**/__tests__/**', '**/*.test.*', '**/*.spec.*', '**/*.d.ts'],
  );
  for (const path of sources) {
    if (path === declarationPath) continue;
    const source = parseSource(path);
    collectReferences(source, importedNames(source, srcDir, declarationPath), referenced);
  }
  const dead = declared.filter((name) => !referenced.has(name));
  if (dead.length) {
    dead.sort().forEach((name) => console.log(`dead flag: ${name}`));
    return 1;
  }
  console.log(`${declared.length} flags, all referenced`);
  return 0;
}

try {
  process.exitCode = main();
} catch (error) {
  console.error(`error: ${error.message}\n${usage}`);
  process.exitCode = 2;
}
