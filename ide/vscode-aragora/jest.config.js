/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/src'],
  testMatch: ['**/*.test.ts'],
  moduleFileExtensions: ['ts', 'js', 'json'],
  transform: {
    '^.+\\.ts$': [
      'ts-jest',
      {
        tsconfig: {
          // Override tsconfig for tests (no vscode types needed)
          module: 'commonjs',
          target: 'ES2022',
          lib: ['ES2022'],
          esModuleInterop: true,
          strict: true,
          skipLibCheck: true,
          moduleResolution: 'node',
        },
      },
    ],
  },
  // Don't try to import actual vscode module
  moduleNameMapper: {
    '^vscode$': '<rootDir>/src/test/vscode.mock.ts',
  },
  // junit.xml is git-ignored by the repository root .gitignore.
  reporters: [
    'default',
    ['jest-junit', { outputDirectory: '<rootDir>', outputName: 'junit.xml' }],
  ],
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/test/**',
    '!src/extension.ts',
    '!src/**/*.d.ts',
  ],
  coverageThreshold: {
    global: {
      branches: 50,
      functions: 50,
      lines: 50,
      statements: 50,
    },
  },
};
