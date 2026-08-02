package ports

import "time"

// Clock exists so the application layer never calls time.Now()
// directly — tests inject a frozen clock; production wires a real
// one. Identical pattern to the standard library's testing/synctest.
type Clock interface {
	Now() time.Time
}
