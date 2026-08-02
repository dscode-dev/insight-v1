package preferences

import (
	"context"

	"github.com/google/uuid"
)

type Repository interface {
	// Get lazily UPSERTs a default row when none exists, so it never
	// returns a "not found" — callers can rely on a typed result.
	Get(ctx context.Context, userID uuid.UUID) (Preferences, error)
	// Update applies the patch + returns the resulting row. Unset
	// fields on the Update are left intact at the DB.
	Update(ctx context.Context, userID uuid.UUID, patch Update) (Preferences, error)
}
