#!/usr/bin/env npx ts-node
/**
 * Build-time Environment Validation Script
 *
 * Runs before production builds to catch missing or misconfigured
 * environment variables. Prevents deploying broken builds.
 *
 * Usage:
 *   npx ts-node scripts/validate-env.ts
 *   npm run validate-env
 *
 * Exit codes:
 *   0 - All validations passed
 *   1 - Missing required variables (production only)
 *   2 - Invalid variable format
 */

interface EnvVar {
  name: string;
  required: boolean;
  description: string;
  validate?: (value: string) => string | null; // Returns error message or null
}

const ENV_VARS: EnvVar[] = [
  {
    name: 'NEXT_PUBLIC_API_URL',
    required: true,
    description: 'Backend API URL (e.g., https://api.aragora.ai)',
    validate: (value) => {
      if (!value.startsWith('http://') && !value.startsWith('https://')) {
        return 'Must be a valid HTTP/HTTPS URL';
      }
      if (value.includes('localhost') && process.env.NODE_ENV === 'production') {
        return 'Cannot use localhost in production';
      }
      return null;
    },
  },
  {
    name: 'NEXT_PUBLIC_WS_URL',
    required: true,
    description: 'WebSocket URL (e.g., wss://api.aragora.ai/ws)',
    validate: (value) => {
      if (!value.startsWith('ws://') && !value.startsWith('wss://')) {
        return 'Must be a valid WS/WSS URL';
      }
      if (value.includes('localhost') && process.env.NODE_ENV === 'production') {
        return 'Cannot use localhost in production';
      }
      return null;
    },
  },
  {
    name: 'NEXT_PUBLIC_SUPABASE_URL',
    required: false,
    description: 'Supabase project URL for persistence',
    validate: (value) => {
      if (!value.includes('supabase.co') && !value.startsWith('http')) {
        return 'Must be a valid Supabase URL';
      }
      return null;
    },
  },
  { name: 'NEXT_PUBLIC_SUPABASE_ANON_KEY', required: false, description: 'Supabase anonymous key' },
  {
    name: 'NEXT_PUBLIC_CONTROL_PLANE_WS_URL',
    required: false,
    description: 'Control plane WebSocket URL',
  },
];

function validateEnv(): boolean {
  const isProduction = process.env.NODE_ENV === 'production';
  const errors: string[] = [];
  const warnings: string[] = [];

  console.log('\n🔍 Validating environment variables...\n');
  console.log(`   Environment: ${isProduction ? 'PRODUCTION' : 'development'}\n`);

  for (const envVar of ENV_VARS) {
    const value = process.env[envVar.name];
    const isSet = value !== undefined && value !== '';

    if (!isSet) {
      if (envVar.required && isProduction) {
        errors.push(`❌ ${envVar.name} - MISSING (required in production)`);
        console.log(`   ${envVar.name}: ${envVar.description}`);
      } else if (envVar.required) {
        warnings.push(`⚠️  ${envVar.name} - not set (will use localhost fallback)`);
      } else {
        console.log(`   ○ ${envVar.name} - not set (optional)`);
      }
    } else {
      // Validate format if validator exists
      if (envVar.validate) {
        const validationError = envVar.validate(value);
        if (validationError) {
          errors.push(`❌ ${envVar.name} = "${value}" - ${validationError}`);
        } else {
          console.log(`   ✓ ${envVar.name} = "${maskSensitive(value)}"`);
        }
      } else {
        console.log(`   ✓ ${envVar.name} = "${maskSensitive(value)}"`);
      }
    }
  }

  console.log('');

  // Print warnings
  if (warnings.length > 0) {
    console.log('Warnings:');
    warnings.forEach((w) => console.log(`   ${w}`));
    console.log('');
  }

  // Print errors
  if (errors.length > 0) {
    console.log('Errors:');
    errors.forEach((e) => console.log(`   ${e}`));
    console.log('');
    console.log('❌ Environment validation FAILED\n');
    return false;
  }

  console.log('✅ Environment validation passed\n');
  return true;
}

function maskSensitive(value: string): string {
  // Mask API keys and tokens
  if (value.length > 20) {
    return value.substring(0, 8) + '...' + value.substring(value.length - 4);
  }
  return value;
}

// Run validation
const isValid = validateEnv();
process.exit(isValid ? 0 : 1);
