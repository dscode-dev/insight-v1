// Package clock — system-clock adapter for ports.Clock.
package clock

import "time"

type System struct{}

func System_() *System { return &System{} }

func (System) Now() time.Time { return time.Now().UTC() }
