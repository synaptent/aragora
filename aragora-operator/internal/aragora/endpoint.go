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

package aragora

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
)

// ErrInvalidEndpoint is wrapped by the errors ValidateEndpoint returns.
var ErrInvalidEndpoint = errors.New("invalid Aragora API endpoint")

// ValidateEndpoint reports whether endpoint can be the control-plane base
// URL. The client appends each API path to it as text, so it must be an
// absolute http or https URL with a host and without a query or fragment,
// not even an empty one: the path would land inside them. A username and
// password are allowed. The error never quotes endpoint, which can hold
// credentials.
func ValidateEndpoint(endpoint string) error {
	u, err := url.Parse(endpoint)
	switch {
	case err != nil:
		// url.Parse errors quote their input.
		return fmt.Errorf("%w: it does not parse as a URL", ErrInvalidEndpoint)
	case u.Scheme != "http" && u.Scheme != "https":
		return fmt.Errorf("%w: the scheme must be http or https", ErrInvalidEndpoint)
	case u.Host == "":
		return fmt.Errorf("%w: it has no host", ErrInvalidEndpoint)
	case u.RawQuery != "" || u.ForceQuery:
		return fmt.Errorf("%w: it has a query", ErrInvalidEndpoint)
	case u.Fragment != "" || strings.Contains(endpoint, "#"):
		// url.Parse drops an empty fragment, so look for the "#" itself.
		return fmt.Errorf("%w: it has a fragment", ErrInvalidEndpoint)
	}
	return nil
}
