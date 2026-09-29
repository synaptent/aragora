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

package main

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"strings"
	"testing"
	"time"

	"k8s.io/client-go/rest"
)

// flagHelpBlock returns the lines --help prints for one flag: its "  -name"
// line and the indented usage lines under it.
func flagHelpBlock(help, name string) string {
	var block []string
	in := false
	for _, line := range strings.Split(help, "\n") {
		switch {
		case strings.HasPrefix(line, "  -"+name+" ") || line == "  -"+name:
			in = true
		case strings.HasPrefix(line, "  -"):
			in = false
		}
		if in {
			block = append(block, line)
		}
	}
	return strings.Join(block, "\n")
}

func TestHelpListsPprofAddrWithEmptyDefault(t *testing.T) {
	fs := flag.NewFlagSet("aragora-operator", flag.ContinueOnError)
	var out bytes.Buffer
	fs.SetOutput(&out)
	bindFlags(fs)

	if err := fs.Parse([]string{"--help"}); !errors.Is(err, flag.ErrHelp) {
		t.Fatalf("Parse(--help) = %v, want flag.ErrHelp", err)
	}
	help := out.String()

	for _, name := range []string{"pprof-addr", "metrics-bind-address", "health-probe-bind-address", "kubeconfig-wait"} {
		if flagHelpBlock(help, name) == "" {
			t.Fatalf("--help does not list -%s:\n%s", name, help)
		}
	}
	pprof := flagHelpBlock(help, "pprof-addr")
	if strings.Contains(pprof, "(default") {
		t.Fatalf("-pprof-addr shows a default, want none (empty = off):\n%s", pprof)
	}
	if f := fs.Lookup("pprof-addr"); f == nil || f.DefValue != "" {
		t.Fatalf("-pprof-addr default = %+v, want empty", f)
	}
	t.Logf("--help lists:\n%s", pprof)
}

func TestPprofAddrFlagAcceptsBothSpellings(t *testing.T) {
	for _, arg := range []string{"--pprof-addr=127.0.0.1:6060", "-pprof-addr=127.0.0.1:6060"} {
		fs := flag.NewFlagSet("aragora-operator", flag.ContinueOnError)
		o := bindFlags(fs)
		if err := fs.Parse([]string{arg}); err != nil {
			t.Fatalf("Parse(%s): %v", arg, err)
		}
		if o.pprofAddr != "127.0.0.1:6060" {
			t.Fatalf("Parse(%s): pprofAddr = %q", arg, o.pprofAddr)
		}
	}
}

func TestWaitForKubeConfigReturnsOnceAvailable(t *testing.T) {
	want := &rest.Config{Host: "https://example.invalid"}
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		if calls < 3 {
			return nil, errors.New("no kubeconfig yet")
		}
		return want, nil
	}

	got, err := waitForKubeConfig(context.Background(), load, time.Second, time.Millisecond)
	if err != nil || got != want {
		t.Fatalf("waitForKubeConfig = %v, %v; want the config on the third attempt", got, err)
	}
	if calls != 3 {
		t.Fatalf("loader called %d times, want 3", calls)
	}
}

func TestWaitForKubeConfigGivesUpAfterWait(t *testing.T) {
	loadErr := errors.New("no configuration has been provided")
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		return nil, loadErr
	}

	start := time.Now()
	_, err := waitForKubeConfig(context.Background(), load, 50*time.Millisecond, 10*time.Millisecond)
	if !errors.Is(err, loadErr) {
		t.Fatalf("waitForKubeConfig error = %v, want it to wrap the last load error", err)
	}
	if calls < 2 {
		t.Fatalf("loader called %d times, want retries within the wait", calls)
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("waitForKubeConfig took %s, want about the 50ms wait", elapsed)
	}
}

func TestWaitForKubeConfigZeroWaitTriesOnce(t *testing.T) {
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		return nil, errors.New("missing")
	}
	if _, err := waitForKubeConfig(context.Background(), load, 0, time.Millisecond); err == nil {
		t.Fatal("waitForKubeConfig succeeded, want an error")
	}
	if calls != 1 {
		t.Fatalf("loader called %d times with a zero wait, want 1", calls)
	}
}

func TestWaitForKubeConfigStopsOnCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		cancel()
		return nil, errors.New("missing")
	}
	start := time.Now()
	if _, err := waitForKubeConfig(ctx, load, time.Minute, 10*time.Second); err == nil {
		t.Fatal("waitForKubeConfig succeeded, want an error")
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("waitForKubeConfig ignored cancellation for %s", elapsed)
	}
}
