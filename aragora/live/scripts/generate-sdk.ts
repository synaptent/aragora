#!/usr/bin/env ts-node
/**
 * SDK Generator for Aragora API
 *
 * Generates TypeScript types and a type-safe API client from the OpenAPI spec.
 *
 * Usage:
 *   npx ts-node scripts/generate-sdk.ts
 *   npm run generate:sdk
 */

import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'js-yaml';

interface OpenAPISchema {
  type?: string;
  format?: string;
  $ref?: string;
  properties?: Record<string, OpenAPISchema>;
  items?: OpenAPISchema;
  required?: string[];
  enum?: string[];
  additionalProperties?: boolean | OpenAPISchema;
  description?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  default?: unknown;
}

interface OpenAPIParameter {
  name: string;
  in: 'path' | 'query' | 'header' | 'cookie';
  required?: boolean;
  schema: OpenAPISchema;
  description?: string;
}

interface OpenAPIRequestBody {
  required?: boolean;
  content: { 'application/json'?: { schema: OpenAPISchema } };
}

interface OpenAPIOperation {
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  security?: Array<Record<string, string[]>>;
  parameters?: OpenAPIParameter[];
  requestBody?: OpenAPIRequestBody;
  responses: Record<
    string,
    { description: string; content?: { 'application/json'?: { schema: OpenAPISchema } } }
  >;
}

interface OpenAPIPath {
  get?: OpenAPIOperation;
  post?: OpenAPIOperation;
  put?: OpenAPIOperation;
  delete?: OpenAPIOperation;
  patch?: OpenAPIOperation;
}

interface OpenAPISpec {
  openapi: string;
  info: { title: string; version: string };
  paths: Record<string, OpenAPIPath>;
  components?: { schemas?: Record<string, OpenAPISchema> };
}

// Convert OpenAPI type to TypeScript type
function schemaToType(
  schema: OpenAPISchema,
  schemas: Record<string, OpenAPISchema>,
  indent = '',
): string {
  if (schema.$ref) {
    const refName = schema.$ref.replace('#/components/schemas/', '');
    return refName;
  }

  if (schema.enum) {
    return schema.enum.map((e) => `'${e}'`).join(' | ');
  }

  switch (schema.type) {
    case 'string':
      if (schema.format === 'date-time') return 'string';
      return 'string';
    case 'integer':
    case 'number':
      return 'number';
    case 'boolean':
      return 'boolean';
    case 'array':
      if (schema.items) {
        const itemType = schemaToType(schema.items, schemas, indent);
        return `${itemType}[]`;
      }
      return 'unknown[]';
    case 'object':
      if (schema.additionalProperties) {
        if (typeof schema.additionalProperties === 'boolean') {
          return 'Record<string, unknown>';
        }
        const valueType = schemaToType(schema.additionalProperties, schemas, indent);
        return `Record<string, ${valueType}>`;
      }
      if (schema.properties) {
        const props = Object.entries(schema.properties)
          .map(([key, prop]) => {
            const optional = !schema.required?.includes(key) ? '?' : '';
            const propType = schemaToType(prop, schemas, indent + '  ');
            const comment = prop.description ? `  /** ${prop.description} */\n${indent}  ` : '';
            return `${comment}${key}${optional}: ${propType}`;
          })
          .join(`;\n${indent}  `);
        return `{\n${indent}  ${props};\n${indent}}`;
      }
      return 'Record<string, unknown>';
    default:
      return 'unknown';
  }
}

// Generate TypeScript interface from schema
function generateInterface(
  name: string,
  schema: OpenAPISchema,
  schemas: Record<string, OpenAPISchema>,
): string {
  const typeBody = schemaToType(schema, schemas, '');
  if (typeBody.startsWith('{')) {
    return `export interface ${name} ${typeBody}`;
  }
  return `export type ${name} = ${typeBody};`;
}

// Generate operation ID from path and method
function generateOperationId(method: string, path: string): string {
  const parts = path
    .replace(/^\/api\//, '')
    .replace(/\{([^}]+)\}/g, 'By$1')
    .split('/')
    .filter(Boolean);

  const camelCase = parts
    .map((part, i) => {
      const cleaned = part.replace(/-/g, '_');
      if (i === 0) return cleaned;
      return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
    })
    .join('');

  return method.toLowerCase() + camelCase.charAt(0).toUpperCase() + camelCase.slice(1);
}

// Main generation function
async function generate() {
  const specPath = path.resolve(__dirname, '../../server/openapi.yaml');
  const outputDir = path.resolve(__dirname, '../src/api/generated');

  console.log('Reading OpenAPI spec from:', specPath);

  if (!fs.existsSync(specPath)) {
    console.error('OpenAPI spec not found at:', specPath);
    process.exit(1);
  }

  const specContent = fs.readFileSync(specPath, 'utf-8');
  const spec = yaml.load(specContent) as OpenAPISpec;

  console.log(`Found ${Object.keys(spec.paths).length} paths`);

  const schemas = spec.components?.schemas || {};
  const types: string[] = [];
  const operations: string[] = [];

  // Generate types from schemas
  types.push('// Auto-generated types from OpenAPI spec');
  types.push('// DO NOT EDIT - regenerate with: npm run generate:sdk');
  types.push('');

  for (const [name, schema] of Object.entries(schemas)) {
    types.push(generateInterface(name, schema, schemas));
    types.push('');
  }

  // Generate API client methods
  operations.push(`/**
 * Auto-generated Aragora API client
 * DO NOT EDIT - regenerate with: npm run generate:sdk
 */

import type * as Types from './types';

export interface ApiClientConfig {
  baseUrl: string;
  getAuthToken?: () => string | null;
  onError?: (error: Error) => void;
}

export interface RequestOptions {
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export class AragoraApiClient {
  private config: ApiClientConfig;

  constructor(config: ApiClientConfig) {
    this.config = config;
  }

  private async request<T>(
    method: string,
    path: string,
    options: RequestOptions & { body?: unknown; query?: Record<string, string | number | undefined> } = {}
  ): Promise<T> {
    let url = \`\${this.config.baseUrl}\${path}\`;

    // Add query params
    if (options.query) {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(options.query)) {
        if (value !== undefined) {
          params.append(key, String(value));
        }
      }
      const queryString = params.toString();
      if (queryString) {
        url += \`?\${queryString}\`;
      }
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    // Add auth token if available
    const token = this.config.getAuthToken?.();
    if (token) {
      headers['Authorization'] = \`Bearer \${token}\`;
    }

    const response = await fetch(url, {
      method,
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });

    if (!response.ok) {
      const error = new Error(\`API error: \${response.status} \${response.statusText}\`);
      this.config.onError?.(error);
      throw error;
    }

    return response.json();
  }
`);

  // Process each path
  for (const [pathTemplate, pathItem] of Object.entries(spec.paths)) {
    for (const [method, operation] of Object.entries(pathItem)) {
      if (!operation || typeof operation !== 'object') continue;
      const op = operation as OpenAPIOperation;

      const operationId = op.operationId || generateOperationId(method, pathTemplate);
      const methodUpper = method.toUpperCase();

      // Extract path params
      const pathParams = (op.parameters || []).filter((p) => p.in === 'path');
      const queryParams = (op.parameters || []).filter((p) => p.in === 'query');
      const hasBody = !!op.requestBody;
      const requiresAuth = op.security && op.security.length > 0;

      // Build function signature
      const params: string[] = [];

      // Path params
      for (const param of pathParams) {
        const type = schemaToType(param.schema, schemas);
        params.push(`${param.name}: ${type}`);
      }

      // Query params as object
      if (queryParams.length > 0) {
        const queryType = queryParams
          .map((p) => {
            const optional = !p.required ? '?' : '';
            const type = schemaToType(p.schema, schemas);
            return `${p.name}${optional}: ${type}`;
          })
          .join('; ');
        params.push(`query?: { ${queryType} }`);
      }

      // Request body
      if (hasBody) {
        const bodySchema = op.requestBody?.content?.['application/json']?.schema;
        if (bodySchema) {
          const bodyType = schemaToType(bodySchema, schemas);
          const optional = !op.requestBody?.required ? '?' : '';
          params.push(`body${optional}: ${bodyType}`);
        }
      }

      // Request options
      params.push('options?: RequestOptions');

      // Response type
      let responseType = 'unknown';
      const successResponse = op.responses['200'] || op.responses['201'];
      if (successResponse?.content?.['application/json']?.schema) {
        responseType = schemaToType(successResponse.content['application/json'].schema, schemas);
      }

      // Build path with params
      let pathWithParams = pathTemplate;
      for (const param of pathParams) {
        pathWithParams = pathWithParams.replace(`{${param.name}}`, `\${${param.name}}`);
      }

      // Generate method
      const jsDoc = [
        '  /**',
        op.summary ? `   * ${op.summary}` : '',
        op.description ? `   * ${op.description}` : '',
        requiresAuth ? '   * @requires Authentication' : '',
        '   */',
      ]
        .filter(Boolean)
        .join('\n');

      const queryArg = queryParams.length > 0 ? ', query' : '';
      const bodyArg = hasBody ? ', body' : '';

      operations.push(`
${jsDoc}
  async ${operationId}(${params.join(', ')}): Promise<${responseType}> {
    return this.request<${responseType}>('${methodUpper}', \`${pathWithParams}\`, { ...options${queryArg ? `, query: query as Record<string, string | number | undefined>` : ''}${bodyArg ? `, body` : ''} });
  }`);
    }
  }

  operations.push(`
}

// Default instance factory
export function createApiClient(config: Partial<ApiClientConfig> = {}): AragoraApiClient {
  return new AragoraApiClient({
    baseUrl: config.baseUrl || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080',
    ...config,
  });
}
`);

  // Write output files
  fs.mkdirSync(outputDir, { recursive: true });

  const typesPath = path.join(outputDir, 'types.ts');
  fs.writeFileSync(typesPath, types.join('\n'));
  console.log('Generated types:', typesPath);

  const clientPath = path.join(outputDir, 'client.ts');
  fs.writeFileSync(clientPath, operations.join('\n'));
  console.log('Generated client:', clientPath);

  // Generate index file
  const indexContent = `// Auto-generated - DO NOT EDIT
export * from './types';
export * from './client';
`;
  const indexPath = path.join(outputDir, 'index.ts');
  fs.writeFileSync(indexPath, indexContent);
  console.log('Generated index:', indexPath);

  console.log('\nSDK generation complete!');
}

generate().catch(console.error);
