/*
Copyright 2024 Aragora.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package observability

// Test helpers shared with the external observability_test package, which
// can see exported names from this package's _test files.

import (
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/go-logr/logr"
	"github.com/go-logr/logr/funcr"
)

// UnsetEnv removes key for the rest of the test and restores it afterwards;
// t.Setenv cannot express "unset".
func UnsetEnv(t *testing.T, key string) {
	t.Helper()
	if old, ok := os.LookupEnv(key); ok {
		t.Cleanup(func() { _ = os.Setenv(key, old) })
	} else {
		t.Cleanup(func() { _ = os.Unsetenv(key) })
	}
	if err := os.Unsetenv(key); err != nil {
		t.Fatalf("unset %s: %v", key, err)
	}
}

// LogLines collects what a logger writes, one entry per log call.
type LogLines struct {
	mu    sync.Mutex
	lines []string
}

// Logger returns a logger that records into l.
func (l *LogLines) Logger() logr.Logger {
	return funcr.New(func(prefix, args string) {
		l.mu.Lock()
		defer l.mu.Unlock()
		l.lines = append(l.lines, strings.TrimSpace(prefix+" "+args))
	}, funcr.Options{})
}

// AssertOne fails t unless exactly one line was logged and it contains want.
func (l *LogLines) AssertOne(t *testing.T, want string) {
	t.Helper()
	l.mu.Lock()
	defer l.mu.Unlock()
	if len(l.lines) != 1 || !strings.Contains(l.lines[0], want) {
		t.Fatalf("log lines = %q, want exactly one line containing %q", l.lines, want)
	}
	t.Logf("logged: %s", l.lines[0])
}
