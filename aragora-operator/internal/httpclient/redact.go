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

package httpclient

import (
	"errors"
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

// unparsableURL stands in for a URL in a message that cannot be reduced to
// its EndpointLabel.
const unparsableURL = "[unparsable URL]"

const urlScheme = `[A-Za-z][A-Za-z0-9+.-]*://`

// urlInText matches URLs as net/http, retryablehttp and url.Parse put them in
// messages: Go-quoted ("..." with backslash escapes, as %q writes them) or
// bare. A bare URL runs to the next white space, because Go keeps a raw
// query as is and a query can hold quotes, apostrophes and other
// punctuation.
var urlInText = regexp.MustCompile(`"` + urlScheme + `(?:[^"\\]|\\.)*"|` + urlScheme + `\S+`)

// wholeURL matches a log value that is a URL from its first character, such
// as retryablehttp's url field. Such a value is labelled as a whole.
var wholeURL = regexp.MustCompile(`^` + urlScheme)

// EndpointLabel returns endpoint as scheme://host[:port]/path, a form that is
// safe to log: the userinfo, query and fragment, which can carry credentials,
// are dropped. It returns fallback when endpoint does not parse as an
// absolute URL with a host.
func EndpointLabel(endpoint, fallback string) string {
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return fallback
	}
	return safeURL(u)
}

func safeURL(u *url.URL) string {
	return (&url.URL{Scheme: u.Scheme, Host: u.Host, Path: u.Path, RawPath: u.RawPath}).String()
}

// redactURLs replaces every URL in s with its EndpointLabel, quoted again
// when it was quoted.
func redactURLs(s string) string {
	return urlInText.ReplaceAllStringFunc(s, func(match string) string {
		if match[0] != '"' {
			return EndpointLabel(match, unparsableURL)
		}
		raw, err := strconv.Unquote(match)
		if err != nil {
			raw = match[1 : len(match)-1]
		}
		return strconv.Quote(EndpointLabel(raw, unparsableURL))
	})
}

// RedactError returns err with every URL in its message reduced to its
// EndpointLabel. errors.Is and errors.As still reach the original error. An
// error whose message holds no URL is returned as is.
func RedactError(err error) error {
	if err == nil {
		return nil
	}
	msg := err.Error()
	var uerr *url.Error
	if errors.As(err, &uerr) && uerr.URL != "" {
		// url.Parse reports its raw input, which can hold characters that end
		// a bare urlInText match early, such as a space in an unescaped
		// password.
		label := EndpointLabel(uerr.URL, unparsableURL)
		quoted := strconv.Quote(uerr.URL)
		msg = strings.ReplaceAll(msg, quoted[1:len(quoted)-1], label)
		msg = strings.ReplaceAll(msg, uerr.URL, label)
	}
	msg = redactURLs(msg)
	if msg == err.Error() {
		return err
	}
	return &redactedError{msg: msg, err: err}
}

type redactedError struct {
	msg string
	err error
}

func (e *redactedError) Error() string { return e.msg }
func (e *redactedError) Unwrap() error { return e.err }

// redactLogValues returns a copy of keysAndValues in which the URLs in
// string and error values are reduced to their EndpointLabel. A string value
// that starts with a URL is parsed and labelled as a whole.
func redactLogValues(keysAndValues []interface{}) []interface{} {
	out := make([]interface{}, len(keysAndValues))
	copy(out, keysAndValues)
	for i := 1; i < len(out); i += 2 {
		switch v := out[i].(type) {
		case string:
			if wholeURL.MatchString(v) {
				out[i] = EndpointLabel(v, unparsableURL)
			} else {
				out[i] = redactURLs(v)
			}
		case error:
			out[i] = RedactError(v)
		}
	}
	return out
}
